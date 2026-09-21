"""Anonimização de arquivos DICOM antes de entrar no miniPACS.

A política do projeto é trabalhar só com dados anonimizados. Este módulo existe
para tornar isso mecânico em vez de depender de disciplina humana: passe a pasta
por aqui *antes* de importar qualquer coisa nova.

O que faz:

* remove ou pseudonimiza (hash com sal) os campos identificáveis;
* remapeia os UIDs de forma **determinística** — o mesmo UID de origem sempre
  vira o mesmo UID de destino, então estudo/série/instância continuam
  agrupados corretamente, mas não dá para voltar ao original sem o sal;
* remove tags privadas e overlays (podem carregar identificação);
* marca o resultado com ``PatientIdentityRemoved = YES``;
* avisa quando o arquivo declara texto queimado na imagem
  (``BurnedInAnnotation = YES``), que nenhum script de tag resolve.

Uso:

    python -m metadata.anonymize --input bruto/ --output anonimizado/

Limitação honesta: isto cobre o cabeçalho, não os pixels. Não é um
de-identificador certificado (perfil completo do DICOM PS3.15 E.1) e não
substitui validação de compliance se um dia isso tocar dado real.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import pydicom
    from pydicom.dataset import Dataset
    from pydicom.uid import generate_uid
except ImportError:  # pragma: no cover
    print("ERRO: a biblioteca 'pydicom' não foi encontrada.")
    print("Instale com: pip install -r requirements.txt")
    sys.exit(1)

from .extract_metadata import iter_dicom_files

#: Zeradas (mantém a tag, esvazia o valor) — alguns softwares exigem a presença.
BLANK_TAGS: Sequence[str] = (
    "PatientBirthDate",
    "PatientBirthTime",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "PatientMotherBirthName",
    "ReferringPhysicianName",
    "ReferringPhysicianAddress",
    "ReferringPhysicianTelephoneNumbers",
    "PerformingPhysicianName",
    "NameOfPhysiciansReadingStudy",
    "OperatorsName",
    "RequestingPhysician",
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "StationName",
    "DeviceSerialNumber",
    "OtherPatientIDs",
    "OtherPatientNames",
    "PatientComments",
    "StudyComments",
    "AdditionalPatientHistory",
    "MedicalRecordLocator",
    "MilitaryRank",
    "EthnicGroup",
    "Occupation",
    "ResponsiblePerson",
    "ResponsibleOrganization",
)

#: Removidas por completo.
REMOVE_TAGS: Sequence[str] = (
    "IssuerOfPatientID",
    "InsurancePlanIdentification",
    "PatientInsurancePlanCodeSequence",
    "PatientReligiousPreference",
    "ContentSequence",
    "ReferencedPatientSequence",
    "RequestAttributesSequence",
    "SourceImageSequence",
    "OriginalAttributesSequence",
    "PersonName",
    "VerifyingObserverSequence",
)

#: UIDs que NUNCA podem ser remapeados (quebram a leitura do arquivo).
PROTECTED_UID_KEYWORDS = {
    "SOPClassUID",
    "MediaStorageSOPClassUID",
    "TransferSyntaxUID",
    "ImplementationClassUID",
    "SpecificCharacterSet",
}

DATE_POLICIES = ("year", "remove", "shift", "keep")


# ---------------------------------------------------------------------------
# Pseudonimização
# ---------------------------------------------------------------------------

def make_salt() -> str:
    """Gera um sal aleatório novo (guarde-o se quiser reprocessar igual)."""
    return secrets.token_hex(16)


def pseudo_id(value: str, salt: str, length: int = 12) -> str:
    """Hash estável e irreversível (sem o sal) de um identificador."""
    digest = hashlib.sha256(f"{salt}|{value}".encode("utf-8")).hexdigest()
    return digest[:length].upper()


def _remap_uid(uid: str, salt: str, cache: Dict[str, str]) -> str:
    """UID novo, determinístico para o par (sal, uid original)."""
    if uid not in cache:
        seed = hashlib.sha256(f"{salt}|uid|{uid}".encode("utf-8")).hexdigest()
        cache[uid] = generate_uid(entropy_srcs=[seed])
    return cache[uid]


def _shift_date(value: str, days: int) -> str:
    """Desloca uma data DICOM (YYYYMMDD) por N dias, preservando intervalos."""
    from datetime import datetime, timedelta

    try:
        parsed = datetime.strptime(str(value)[:8], "%Y%m%d")
    except ValueError:
        return ""
    return (parsed + timedelta(days=days)).strftime("%Y%m%d")


def _apply_date_policy(ds: "Dataset", policy: str, shift_days: int) -> None:
    if policy == "keep":
        return
    for element in ds:
        if element.VR != "DA" or not element.value:
            continue
        raw = str(element.value)
        if policy == "remove":
            element.value = ""
        elif policy == "year":
            element.value = raw[:4] + "0101" if len(raw) >= 4 else ""
        elif policy == "shift":
            element.value = _shift_date(raw, shift_days)
    # Horários exatos também são quase-identificadores
    if policy in ("remove", "year"):
        for element in ds:
            if element.VR == "TM" and element.value:
                element.value = ""


# ---------------------------------------------------------------------------
# Anonimização
# ---------------------------------------------------------------------------

def anonymize_dataset(
    ds: "Dataset",
    salt: str,
    keep_uids: bool = False,
    date_policy: str = "year",
    shift_days: int = 0,
    uid_cache: Optional[Dict[str, str]] = None,
    patient_prefix: str = "ANON",
) -> "Dataset":
    """Anonimiza um dataset **no lugar** e o devolve.

    Args:
        ds: dataset lido com `pydicom.dcmread`.
        salt: sal do hash — o mesmo sal em toda a importação mantém o mesmo
            paciente com o mesmo pseudônimo entre exames diferentes.
        keep_uids: se True, mantém os UIDs originais (útil quando os arquivos
            já vieram anonimizados e você só quer limpar o cabeçalho).
        date_policy: ``year`` (mantém só o ano), ``remove``, ``shift`` ou ``keep``.
        shift_days: dias de deslocamento quando ``date_policy='shift'``.
        uid_cache: dicionário compartilhado entre arquivos da mesma série.
    """
    if date_policy not in DATE_POLICIES:
        raise ValueError(f"date_policy inválida: {date_policy}")

    cache = uid_cache if uid_cache is not None else {}

    # 1. Paciente: pseudônimo estável derivado do ID original
    original_id = str(getattr(ds, "PatientID", "") or "SEM-ID")
    pseudo = f"{patient_prefix}-{pseudo_id(original_id, salt)}"
    ds.PatientID = pseudo
    ds.PatientName = pseudo
    if "AccessionNumber" in ds and ds.AccessionNumber:
        ds.AccessionNumber = pseudo_id(str(ds.AccessionNumber), salt)

    # 2. Campos identificáveis
    for keyword in BLANK_TAGS:
        if keyword in ds:
            ds[keyword].value = ""
    for keyword in REMOVE_TAGS:
        if keyword in ds:
            del ds[keyword]

    # 3. Datas/horas
    _apply_date_policy(ds, date_policy, shift_days)

    # 4. Tags privadas e overlays (podem conter texto identificável)
    ds.remove_private_tags()
    for group in range(0x6000, 0x6100, 2):
        for tag in list(ds.group_dataset(group).keys()):
            del ds[tag]

    # 5. UIDs — determinístico, preserva o agrupamento estudo/série
    if not keep_uids:
        def remap(dataset: "Dataset", element) -> None:
            if element.VR != "UI" or not element.value:
                return
            if element.keyword in PROTECTED_UID_KEYWORDS:
                return
            if isinstance(element.value, str):
                element.value = _remap_uid(element.value, salt, cache)
            else:  # MultiValue de UIDs
                element.value = [_remap_uid(str(v), salt, cache) for v in element.value]

        ds.walk(remap)
        if hasattr(ds, "file_meta") and "MediaStorageSOPInstanceUID" in ds.file_meta:
            ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID

    # 6. Marcação de procedência
    ds.PatientIdentityRemoved = "YES"
    # VR LO: máximo 64 caracteres — mantenha curto.
    ds.DeidentificationMethod = f"dicom-viewer: hash+sal, UIDs, datas={date_policy}"[:64]
    return ds


def has_burned_in_annotation(ds: "Dataset") -> bool:
    return str(getattr(ds, "BurnedInAnnotation", "") or "").upper() == "YES"


def anonymize_folder(
    input_dir: str,
    output_dir: str,
    salt: str,
    keep_uids: bool = False,
    date_policy: str = "year",
    shift_days: int = 0,
    recursive: bool = True,
    dry_run: bool = False,
    verbose: bool = True,
) -> Tuple[int, int, List[str]]:
    """Anonimiza uma pasta inteira preservando a estrutura de subpastas.

    Returns:
        ``(processados, ignorados, avisos)``.
    """
    uid_cache: Dict[str, str] = {}
    processed = skipped = 0
    warnings: List[str] = []
    base = os.path.abspath(input_dir)

    for path in iter_dicom_files(input_dir, recursive=recursive):
        try:
            ds = pydicom.dcmread(path)
        except Exception:
            skipped += 1
            continue

        if has_burned_in_annotation(ds):
            warnings.append(path)

        anonymize_dataset(
            ds,
            salt=salt,
            keep_uids=keep_uids,
            date_policy=date_policy,
            shift_days=shift_days,
            uid_cache=uid_cache,
        )

        if os.path.isfile(base):
            relative = os.path.basename(path)
        else:
            relative = os.path.relpath(path, base)
        destination = os.path.join(output_dir, relative)

        if not dry_run:
            os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
            ds.save_as(destination, enforce_file_format=True)

        processed += 1
        if verbose and processed % 25 == 0:
            print(f"  {processed} arquivos anonimizados")

    return processed, skipped, warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anonymize",
        description="Anonimiza o cabeçalho de arquivos DICOM antes da importação.",
    )
    parser.add_argument("--input", "-i", required=True, help="Pasta ou arquivo de origem.")
    parser.add_argument("--output", "-o", required=True, help="Pasta de destino.")
    parser.add_argument(
        "--salt",
        help="Sal do hash. Sem isto, um sal aleatório é gerado e mostrado na tela.",
    )
    parser.add_argument(
        "--salt-file",
        help="Arquivo com o sal (criado automaticamente se não existir). "
             "Use o mesmo arquivo para manter pseudônimos estáveis entre importações. "
             "NÃO versione este arquivo.",
    )
    parser.add_argument("--keep-uids", action="store_true", help="Não remapear UIDs.")
    parser.add_argument(
        "--date-policy", choices=DATE_POLICIES, default="year",
        help="Tratamento de datas (padrão: year — mantém só o ano).",
    )
    parser.add_argument(
        "--shift-days", type=int, default=0,
        help="Dias de deslocamento quando --date-policy shift.",
    )
    parser.add_argument("--no-recursive", action="store_true", help="Não entrar em subpastas.")
    parser.add_argument("--dry-run", action="store_true", help="Só simula, não grava nada.")
    parser.add_argument("--quiet", "-q", action="store_true")
    return parser


def resolve_salt(args: argparse.Namespace) -> str:
    if args.salt:
        return args.salt
    if args.salt_file:
        if os.path.exists(args.salt_file):
            with open(args.salt_file, "r", encoding="utf-8") as fh:
                salt = fh.read().strip()
            if salt:
                return salt
        salt = make_salt()
        parent = os.path.dirname(os.path.abspath(args.salt_file))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(args.salt_file, "w", encoding="utf-8") as fh:
            fh.write(salt + "\n")
        print(f"Sal novo gravado em {args.salt_file} (não versione este arquivo).")
        return salt
    salt = make_salt()
    print(f"Sal gerado (guarde se quiser reprocessar igual): {salt}")
    return salt


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.exists(args.input):
        print(f"ERRO: caminho não encontrado: {args.input}", file=sys.stderr)
        return 2

    salt = resolve_salt(args)
    processed, skipped, warnings = anonymize_folder(
        args.input,
        args.output,
        salt=salt,
        keep_uids=args.keep_uids,
        date_policy=args.date_policy,
        shift_days=args.shift_days,
        recursive=not args.no_recursive,
        dry_run=args.dry_run,
        verbose=not args.quiet,
    )

    prefixo = "[dry-run] " if args.dry_run else ""
    print(f"{prefixo}{processed} arquivo(s) anonimizado(s), {skipped} ignorado(s).")
    if warnings:
        print(
            f"ATENÇÃO: {len(warnings)} arquivo(s) declaram texto queimado na imagem "
            "(BurnedInAnnotation=YES). O cabeçalho foi limpo, mas os pixels NÃO — "
            "revise visualmente antes de usar:",
            file=sys.stderr,
        )
        for path in warnings[:10]:
            print(f"  {path}", file=sys.stderr)
        if len(warnings) > 10:
            print(f"  ... e mais {len(warnings) - 10}", file=sys.stderr)
    return 0 if processed else 1


if __name__ == "__main__":
    raise SystemExit(main())
