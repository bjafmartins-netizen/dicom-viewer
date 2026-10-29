#!/usr/bin/env python3
"""Confere se um estudo de RM tem o protocolo mínimo para esclerose múltipla.

    python scripts/check_ms_protocol.py --study <StudyInstanceUID ou ID do Orthanc>
    python scripts/check_ms_protocol.py --todos
    python scripts/check_ms_protocol.py --input data/exame

Lê as séries do estudo (no Orthanc ou direto de uma pasta) e verifica a
presença de FLAIR 3D, T1 pós-contraste, SWI/T2* e cobertura do nervo óptico.

A regra de decisão é deliberada: falta de SWI **alerta**, falta de FLAIR 3D ou
de T1+C **bloqueia** — sem essas duas não dá para aplicar os critérios de
McDonald 2024 com segurança.

Código de saída: 0 protocolo viável, 1 bloqueado, 2 erro de uso.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

# Permite rodar como `python scripts/check_ms_protocol.py` a partir da raiz
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metadata.extract_metadata import group_by_series, scan_folder  # noqa: E402
from metadata.orthanc_client import DEFAULT_URL, OrthancClient, OrthancError  # noqa: E402

#: Marcas de fabricante para aquisição volumétrica — nem todo equipamento
#: escreve "3D" na descrição da série.
MARCAS_3D = ("3D", "SPACE", "CUBE", "VISTA", "MPRAGE", "BRAVO", "ISO")
MARCAS_SWI = ("SWI", "T2*", "VEN", "SWAN", "MEDIC")
MARCAS_CONTRASTE = ("GD", "+C", "POS", "CONTRAST", "CE")
MARCAS_ORBITA = ("ORBIT", "OPTIC", "NERVO", "DIRECIONAD")


def _texto_da_serie(series: Dict[str, Any]) -> str:
    """Descrição + protocolo em maiúsculas: onde o nome da sequência aparece."""
    tags = series.get("MainDicomTags", {})
    partes = [tags.get("SeriesDescription", ""), tags.get("ProtocolName", "")]
    return " ".join(p for p in partes if p).upper()


def evaluate_ms_protocol(
    series_list: Sequence[Dict[str, Any]],
    study_id: str = "",
    verbose: bool = True,
) -> bool:
    """Avalia se o estudo possui as sequências mínimas exigidas.

    Emite alerta para falta de SWI, mas bloqueia apenas se faltar FLAIR 3D ou
    T1+C.

    Args:
        series_list: séries no formato do Orthanc (``MainDicomTags`` com
            ``SeriesDescription``); ``MRAcquisitionType`` é usado quando
            disponível.
        study_id: identificação mostrada no cabeçalho do relatório.
        verbose: imprime o relatório; False só devolve o resultado.
    """
    has_flair_3d = False
    has_swi = False
    has_t1_gd = False
    has_optic_nerve = False

    for series in series_list:
        description = _texto_da_serie(series)
        # O cabeçalho é mais confiável que o nome dado pelo operador.
        volumetrica = str(
            series.get("MainDicomTags", {}).get("MRAcquisitionType", "")
        ).upper() == "3D"

        if "FLAIR" in description and (
            volumetrica or any(x in description for x in MARCAS_3D)
        ):
            has_flair_3d = True
        if any(x in description for x in MARCAS_SWI):
            has_swi = True
        if "T1" in description and any(x in description for x in MARCAS_CONTRASTE):
            has_t1_gd = True
        if any(x in description for x in MARCAS_ORBITA):
            has_optic_nerve = True

    viavel = has_flair_3d and has_t1_gd

    if verbose:
        # Marcadores em ASCII de propósito: o console do Windows usa cp1252 e
        # quebra com UnicodeEncodeError ao imprimir "✓".
        marca = lambda ok: "[OK]" if ok else "[--]"  # noqa: E731
        print(f"--- ANÁLISE DE PROTOCOLO: ESTUDO {study_id} ---")
        print(f"{marca(has_flair_3d)} FLAIR 3D: {'Sim' if has_flair_3d else 'NÃO'}")
        print(f"{marca(has_t1_gd)} T1 + Contraste: {'Sim' if has_t1_gd else 'NÃO'}")
        print(
            f"{marca(has_optic_nerve)} Cobertura Nervo Óptico: "
            f"{'Sim' if has_optic_nerve else 'NÃO'}"
        )

        # Tratamento específico (Alerta vs Bloqueio)
        if not has_swi:
            print(
                "\n[!] ALERTA NÃO-IMPEDITIVO: Sequência de suscetibilidade "
                "(SWI/T2*) ausente. A pesquisa do Sinal da Veia Central (CVS) e "
                "diferenciação microangiopática ficarão prejudicadas. Prosseguindo."
            )
        else:
            print("[OK] SWI / T2*: Sim")

        if not viavel:
            print(
                "\n[X] BLOQUEIO DE FLUXO: Protocolo insuficiente. A ausência de "
                "FLAIR 3D ou T1+C impede a aplicação segura dos critérios de "
                "McDonald 2024."
            )
        else:
            print("\nSTATUS: Protocolo viável para estruturação do laudo.")

    return viavel


def get_study_series(client: OrthancClient, study_id: str) -> List[Dict[str, Any]]:
    """Séries do estudo no Orthanc, com ``MRAcquisitionType`` acrescentado.

    O Orthanc não guarda ``MRAcquisitionType`` entre as tags principais da
    série, então ele é lido de uma instância de cada série (uma requisição por
    série, não por imagem).
    """
    series_list = client.study_series(study_id)
    for series in series_list:
        instances = series.get("Instances") or []
        if not instances:
            continue
        try:
            tags = client.instance_tags(instances[0])
        except OrthancError:
            continue
        valor = tags.get("MRAcquisitionType")
        if valor:
            series.setdefault("MainDicomTags", {})["MRAcquisitionType"] = valor
    return series_list


def series_from_folder(folder: str) -> List[Dict[str, Any]]:
    """Mesma estrutura, lendo os arquivos direto da pasta (sem servidor)."""
    series: List[Dict[str, Any]] = []
    for linha in group_by_series(scan_folder(folder)):
        series.append(
            {
                "MainDicomTags": {
                    "SeriesDescription": linha.get("SeriesDescription") or "",
                    "ProtocolName": linha.get("ProtocolName") or "",
                    "MRAcquisitionType": linha.get("MRAcquisitionType") or "",
                    "SeriesNumber": linha.get("SeriesNumber") or "",
                },
                "Instances": [None] * int(linha.get("InstanceCount") or 0),
            }
        )
    return series


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_ms_protocol",
        description="Confere o protocolo mínimo de RM para esclerose múltipla.",
    )
    parser.add_argument(
        "--study", "-s", metavar="ID",
        help="Estudo a avaliar: StudyInstanceUID ou ID do Orthanc.",
    )
    parser.add_argument(
        "--todos", action="store_true",
        help="Avalia todos os estudos do servidor.",
    )
    parser.add_argument(
        "--input", "-i", metavar="PASTA",
        help="Lê os arquivos de uma pasta local, sem passar pelo Orthanc.",
    )
    parser.add_argument("--url", default=DEFAULT_URL, help=f"URL do Orthanc (padrão {DEFAULT_URL}).")
    parser.add_argument("--user", help="Usuário, se o Orthanc exigir autenticação.")
    parser.add_argument("--password", help="Senha.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.input:
        if not os.path.isdir(args.input):
            print(f"ERRO: pasta não encontrada: {args.input}", file=sys.stderr)
            return 2
        series = series_from_folder(args.input)
        if not series:
            print(f"ERRO: nenhum DICOM legível em {args.input}", file=sys.stderr)
            return 2
        return 0 if evaluate_ms_protocol(series, args.input) else 1

    if not args.study and not args.todos:
        print(
            "ERRO: informe --study <id>, --todos ou --input <pasta>.",
            file=sys.stderr,
        )
        return 2

    client = OrthancClient(args.url, username=args.user, password=args.password)
    try:
        if args.todos:
            estudos = client.list_studies()
            if not estudos:
                print("Nenhum estudo no servidor.", file=sys.stderr)
                return 2
        else:
            estudos = [client.resolve_study(args.study)]

        bloqueados = 0
        for posicao, study_id in enumerate(estudos):
            if posicao:
                print()
            try:
                tags = client.study_tags(study_id)
            except OrthancError as exc:
                print(f"ERRO: estudo não encontrado ({exc})", file=sys.stderr)
                return 2
            rotulo = (
                tags.get("MainDicomTags", {}).get("StudyDescription")
                or tags.get("MainDicomTags", {}).get("StudyInstanceUID")
                or study_id
            )
            if not evaluate_ms_protocol(get_study_series(client, study_id), rotulo):
                bloqueados += 1
    except OrthancError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2

    return 1 if bloqueados else 0


if __name__ == "__main__":
    raise SystemExit(main())
