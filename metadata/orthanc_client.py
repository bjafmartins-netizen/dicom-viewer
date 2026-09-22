"""Cliente mínimo para o Orthanc (REST) e DICOMweb (STOW-RS).

Usa apenas a biblioteca padrão (`urllib`) — nada de `requests` — para manter o
projeto portátil, rodando de um pendrive com um Python embarcado.

Dois caminhos de envio:

* ``upload_file`` / ``upload_folder`` — API REST própria do Orthanc
  (``POST /instances``): mais simples e mais rápida.
* ``upload_stow`` — DICOMweb padrão (``POST /dicom-web/studies``): funciona com
  qualquer servidor DICOMweb, não só o Orthanc.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .extract_metadata import COMMON_TAGS, iter_dicom_files, tags_for_modality

DEFAULT_URL = "http://localhost:8042"


class OrthancError(RuntimeError):
    """Falha de comunicação com o servidor."""


class OrthancClient:
    """Cliente REST/DICOMweb.

    Args:
        base_url: ex. ``http://localhost:8042``.
        username/password: só se o Orthanc estiver com autenticação ligada.
        timeout: segundos.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = _prefer_ipv4(base_url.rstrip("/"))
        self.timeout = timeout
        self._auth: Optional[str] = None
        if username is not None:
            raw = f"{username}:{password or ''}".encode("utf-8")
            self._auth = "Basic " + base64.b64encode(raw).decode("ascii")

    # -- infraestrutura ----------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[bytes] = None,
        content_type: Optional[str] = None,
    ) -> bytes:
        url = self.base_url + path
        request = urllib.request.Request(url, data=data, method=method)
        if content_type:
            request.add_header("Content-Type", content_type)
        if self._auth:
            request.add_header("Authorization", self._auth)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise OrthancError(f"HTTP {exc.code} em {method} {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OrthancError(
                f"Não consegui falar com {url} ({exc.reason}). "
                "O Orthanc está rodando?"
            ) from exc

    def _get_json(self, path: str) -> Any:
        return json.loads(self._request("GET", path).decode("utf-8"))

    # -- consultas ---------------------------------------------------------

    def system(self) -> Dict[str, Any]:
        """Informações do servidor — serve de teste de conectividade."""
        return self._get_json("/system")

    def statistics(self) -> Dict[str, Any]:
        return self._get_json("/statistics")

    def list_instances(self) -> List[str]:
        return self._get_json("/instances")

    def list_studies(self) -> List[str]:
        return self._get_json("/studies")

    def instance_tags(self, instance_id: str) -> Dict[str, Any]:
        """Tags de uma instância no formato ``{keyword: valor}``."""
        return self._get_json(f"/instances/{instance_id}/simplified-tags")

    def scan_metadata(
        self,
        extra_tags: Optional[Iterable[str]] = None,
        verbose: bool = False,
    ) -> List[Dict[str, Any]]:
        """Monta os mesmos registros de `scan_folder`, mas via API do Orthanc.

        Evita reabrir os arquivos brutos quando eles já estão no miniPACS.
        """
        records: List[Dict[str, Any]] = []
        instances = self.list_instances()
        for index, instance_id in enumerate(instances, start=1):
            try:
                tags = self.instance_tags(instance_id)
            except OrthancError as exc:
                if verbose:
                    print(f"  ignorada {instance_id}: {exc}", file=sys.stderr)
                continue

            record: Dict[str, Any] = {"OrthancInstanceID": instance_id}
            for keyword in COMMON_TAGS:
                record[keyword] = _clean(tags.get(keyword))
            for keyword in tags_for_modality(record.get("Modality")):
                record[keyword] = _clean(tags.get(keyword))
            for keyword in extra_tags or ():
                record[keyword] = _clean(tags.get(keyword))
            records.append(record)

            if verbose and index % 50 == 0:
                print(f"  {index}/{len(instances)} instâncias", file=sys.stderr)
        return records

    # -- envio -------------------------------------------------------------

    def upload_file(self, path: str) -> Dict[str, Any]:
        """Envia um arquivo pela API REST do Orthanc (``POST /instances``)."""
        with open(path, "rb") as fh:
            payload = fh.read()
        raw = self._request("POST", "/instances", payload, "application/dicom")
        return json.loads(raw.decode("utf-8")) if raw else {}

    def upload_stow(self, paths: Sequence[str]) -> bytes:
        """Envia arquivos via STOW-RS (DICOMweb padrão), em um único POST."""
        boundary = uuid.uuid4().hex
        parts: List[bytes] = []
        for path in paths:
            with open(path, "rb") as fh:
                payload = fh.read()
            parts.append(
                f"--{boundary}\r\n"
                "Content-Type: application/dicom\r\n"
                f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8")
                + payload
                + b"\r\n"
            )
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)
        content_type = (
            f'multipart/related; type="application/dicom"; boundary={boundary}'
        )
        return self._request("POST", "/dicom-web/studies", body, content_type)

    def upload_folder(
        self,
        folder: str,
        recursive: bool = True,
        use_stow: bool = False,
        batch_size: int = 20,
        verbose: bool = True,
    ) -> Tuple[int, int]:
        """Envia uma pasta inteira. Devolve ``(enviados, falhas)``."""
        paths = [p for p in iter_dicom_files(folder, recursive=recursive)]
        sent = failed = 0

        if use_stow:
            for start in range(0, len(paths), batch_size):
                lote = paths[start:start + batch_size]
                try:
                    self.upload_stow(lote)
                    sent += len(lote)
                    if verbose:
                        print(f"  STOW-RS: {sent}/{len(paths)}")
                except OrthancError as exc:
                    failed += len(lote)
                    if verbose:
                        print(f"  falha no lote {start}: {exc}", file=sys.stderr)
            return sent, failed

        for path in paths:
            try:
                self.upload_file(path)
                sent += 1
                if verbose and sent % 25 == 0:
                    print(f"  {sent}/{len(paths)} enviados")
            except OrthancError as exc:
                failed += 1
                if verbose:
                    print(f"  falha em {path}: {exc}", file=sys.stderr)
        return sent, failed


def _prefer_ipv4(url: str) -> str:
    """Troca ``localhost`` por ``127.0.0.1``.

    No Windows, ``localhost`` resolve primeiro para ``::1``; o Orthanc só escuta
    em IPv4, e cada requisição perde ~2 s até o fallback — 369 instâncias
    viravam 13 minutos de extração.
    """
    parts = urllib.parse.urlsplit(url)
    if (parts.hostname or "").lower() != "localhost":
        return url
    netloc = "127.0.0.1" + (f":{parts.port}" if parts.port else "")
    if "@" in parts.netloc:
        netloc = parts.netloc.rsplit("@", 1)[0] + "@" + netloc
    return urllib.parse.urlunsplit(parts._replace(netloc=netloc))


# Decimal com dígitos demais: é como o Orthanc imprime tags FD/FL
# (0.90000000000000002 em vez de 0.9).
_FLOAT_LONGO = re.compile(r"[+-]?\d*\.\d{15,}(?:[eE][+-]?\d+)?")


def _clean(value: Any) -> Any:
    """Normaliza o que a API devolve para ficar igual a `scan_folder`.

    String vazia vira None; valores múltiplos (``0.5\\0.5``) viram lista, como
    o MultiValue do pydicom; FD/FL voltam à representação curta do float.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return None  # sequências DICOM não viram coluna de tabela
    text = str(value).strip()
    if not text:
        return None
    if "\\" in text:
        return [_clean_token(v) for v in text.split("\\")]
    return _clean_token(text)


def _clean_token(text: str) -> Optional[str]:
    text = text.strip()
    if _FLOAT_LONGO.fullmatch(text):
        return repr(float(text))
    return text or None
