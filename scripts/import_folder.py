#!/usr/bin/env python3
"""Importa uma pasta inteira de arquivos DICOM para o Orthanc.

    python scripts/import_folder.py --input data/phantom
    python scripts/import_folder.py --input data/phantom --stow
    python scripts/import_folder.py --input data/bruto --anonymize --salt-file .salt

Por padrão usa a API REST do Orthanc (`POST /instances`), que é mais simples e
rápida. Com `--stow`, usa DICOMweb STOW-RS padrão, que funciona com qualquer
servidor DICOMweb (não só o Orthanc).

Com `--anonymize`, os arquivos são anonimizados para uma pasta temporária antes
do envio — nada identificável chega ao servidor.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from typing import Optional, Sequence

# Permite rodar como `python scripts/import_folder.py` a partir da raiz
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metadata.anonymize import anonymize_folder, resolve_salt  # noqa: E402
from metadata.orthanc_client import DEFAULT_URL, OrthancClient, OrthancError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_folder",
        description="Envia uma pasta de arquivos DICOM para o Orthanc/miniPACS.",
    )
    parser.add_argument("--input", "-i", required=True, help="Pasta com os arquivos DICOM.")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"URL do Orthanc (padrão {DEFAULT_URL}).")
    parser.add_argument("--user", help="Usuário, se o Orthanc estiver com autenticação.")
    parser.add_argument("--password", help="Senha.")
    parser.add_argument("--stow", action="store_true", help="Usar STOW-RS (DICOMweb) em vez da API REST.")
    parser.add_argument("--batch-size", type=int, default=20, help="Arquivos por POST no modo STOW-RS.")
    parser.add_argument("--no-recursive", action="store_true", help="Não entrar em subpastas.")
    parser.add_argument(
        "--anonymize", action="store_true",
        help="Anonimizar antes de enviar (recomendado para arquivos novos).",
    )
    parser.add_argument("--salt", help="Sal do hash de anonimização.")
    parser.add_argument("--salt-file", help="Arquivo com o sal (criado se não existir).")
    parser.add_argument(
        "--keep-anonymized",
        help="Pasta onde guardar a cópia anonimizada (senão, é temporária e descartada).",
    )
    parser.add_argument("--quiet", "-q", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    verbose = not args.quiet

    if not os.path.exists(args.input):
        print(f"ERRO: caminho não encontrado: {args.input}", file=sys.stderr)
        return 2

    client = OrthancClient(args.url, username=args.user, password=args.password)

    # Falha cedo e com mensagem clara se o servidor não estiver de pé
    try:
        info = client.system()
        if verbose:
            print(f"Conectado ao Orthanc {info.get('Version')} ({info.get('Name')}) em {args.url}")
    except OrthancError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        print("Suba o servidor antes (pacs/README.md) ou use scripts/start_all.", file=sys.stderr)
        return 3

    source = args.input
    temporary: Optional[str] = None

    if args.anonymize:
        salt = resolve_salt(args)
        destination = args.keep_anonymized
        if destination is None:
            temporary = tempfile.mkdtemp(prefix="dicom-anon-")
            destination = temporary
        if verbose:
            print(f"Anonimizando para {destination} ...")
        processed, skipped, warnings = anonymize_folder(
            args.input, destination, salt=salt,
            recursive=not args.no_recursive, verbose=verbose,
        )
        if verbose:
            print(f"  {processed} anonimizado(s), {skipped} ignorado(s)")
        if warnings:
            print(
                f"ATENÇÃO: {len(warnings)} arquivo(s) com BurnedInAnnotation=YES "
                "(texto queimado nos pixels). Revise antes de usar.",
                file=sys.stderr,
            )
        if not processed:
            print("Nada para enviar.", file=sys.stderr)
            _cleanup(temporary)
            return 1
        source = destination

    try:
        sent, failed = client.upload_folder(
            source,
            recursive=not args.no_recursive,
            use_stow=args.stow,
            batch_size=args.batch_size,
            verbose=verbose,
        )
    finally:
        _cleanup(temporary)

    modo = "STOW-RS" if args.stow else "REST"
    print(f"{sent} instância(s) enviada(s) via {modo}, {failed} falha(s).")

    if verbose and sent:
        try:
            stats = client.statistics()
            print(
                f"Servidor agora: {stats.get('CountStudies')} estudo(s), "
                f"{stats.get('CountSeries')} série(s), "
                f"{stats.get('CountInstances')} instância(s)."
            )
            print(f"Confira em {args.url} (Orthanc Explorer) ou no OHIF.")
        except OrthancError:
            pass

    return 0 if failed == 0 else 1


def _cleanup(path: Optional[str]) -> None:
    if path:
        shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
