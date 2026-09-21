"""Extração de metadados DICOM em lote.

Evolução da parte de leitura do `sico.py`: aqui não há interface gráfica, só
funções puras que recebem um dataset pydicom (ou uma pasta) e devolvem
dicionários prontos para virar CSV/JSON/Parquet/DataFrame.

Uso como biblioteca:

    from metadata import extract_metadata, scan_folder

    registros = scan_folder("C:/exames")

Uso como CLI:

    python -m metadata.extract_metadata --input C:/exames --output metadata.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

try:
    import pydicom
    from pydicom.dataset import Dataset
except ImportError:  # pragma: no cover - mensagem amigável, igual ao sico.py
    print("ERRO: a biblioteca 'pydicom' não foi encontrada.")
    print("Instale com: pip install -r requirements.txt")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

#: Tags lidas para qualquer modalidade (identificação, estudo, série, imagem).
COMMON_TAGS: Sequence[str] = (
    # Paciente (em dataset anonimizado a maioria vem vazia/pseudonimizada)
    "PatientID",
    "PatientName",
    "PatientSex",
    "PatientAge",
    "PatientBirthDate",
    "PatientWeight",
    # Estudo
    "StudyInstanceUID",
    "StudyID",
    "AccessionNumber",
    "StudyDate",
    "StudyTime",
    "StudyDescription",
    "ReferringPhysicianName",
    # Série
    "SeriesInstanceUID",
    "SeriesNumber",
    "SeriesDate",
    "SeriesTime",
    "SeriesDescription",
    "ProtocolName",
    "Modality",
    "BodyPartExamined",
    "Laterality",
    "PatientPosition",
    # Instância
    "SOPInstanceUID",
    "SOPClassUID",
    "InstanceNumber",
    "ImageType",
    # Equipamento
    "Manufacturer",
    "ManufacturerModelName",
    "StationName",
    "InstitutionName",
    "DeviceSerialNumber",
    "SoftwareVersions",
    # Geometria / imagem
    "Rows",
    "Columns",
    "PixelSpacing",
    "SliceThickness",
    "SpacingBetweenSlices",
    "SliceLocation",
    "ImagePositionPatient",
    "ImageOrientationPatient",
    "NumberOfFrames",
    "BitsAllocated",
    "BitsStored",
    "PhotometricInterpretation",
    "RescaleSlope",
    "RescaleIntercept",
    "WindowCenter",
    "WindowWidth",
    "BurnedInAnnotation",
)

#: Tags específicas por modalidade — parâmetros de aquisição que interessam
#: para controle de qualidade, dosimetria e pesquisa.
MODALITY_TAGS: Dict[str, Sequence[str]] = {
    "MR": (
        "MagneticFieldStrength",
        "ScanningSequence",
        "SequenceVariant",
        "ScanOptions",
        "MRAcquisitionType",
        "SequenceName",
        "RepetitionTime",
        "EchoTime",
        "InversionTime",
        "EchoTrainLength",
        "EchoNumbers",
        "FlipAngle",
        "NumberOfAverages",
        "PixelBandwidth",
        "PercentPhaseFieldOfView",
        "AcquisitionMatrix",
        "InPlanePhaseEncodingDirection",
        "ReceiveCoilName",
        "TransmitCoilName",
        "DiffusionBValue",
        "ParallelAcquisitionTechnique",
        "ParallelReductionFactorInPlane",
    ),
    "CT": (
        "KVP",
        "XRayTubeCurrent",
        "ExposureTime",
        "Exposure",
        "CTDIvol",
        "ConvolutionKernel",
        "ReconstructionDiameter",
        "DataCollectionDiameter",
        "SpiralPitchFactor",
        "TableFeedPerRotation",
        "SingleCollimationWidth",
        "TotalCollimationWidth",
        "GantryDetectorTilt",
        "FilterType",
        "ExposureModulationType",
        "ContrastBolusAgent",
    ),
    "PT": (
        "Radiopharmaceutical",
        "RadionuclideTotalDose",
        "RadionuclideHalfLife",
        "DecayCorrection",
        "Units",
        "SeriesType",
        "ReconstructionMethod",
        "AttenuationCorrectionMethod",
        "ActualFrameDuration",
    ),
    "MG": (
        "KVP",
        "Exposure",
        "ExposureTime",
        "XRayTubeCurrent",
        "AnodeTargetMaterial",
        "FilterMaterial",
        "CompressionForce",
        "BodyPartThickness",
        "ViewPosition",
        "OrganDose",
        "EntranceDoseInmGy",
        "DetectorType",
        "GridID",
    ),
    "US": (
        "TransducerType",
        "TransducerFrequency",
        "MechanicalIndex",
        "ThermalIndex",
        "DepthOfScanField",
        "UltrasoundColorDataPresent",
        "NumberOfStages",
    ),
    "NM": (
        "Radiopharmaceutical",
        "RadionuclideTotalDose",
        "EnergyWindowName",
        "NumberOfFramesInRotation",
        "ActualFrameDuration",
    ),
}

#: Radiografia digital e derivados compartilham o mesmo conjunto.
_XRAY_TAGS: Sequence[str] = (
    "KVP",
    "Exposure",
    "ExposureTime",
    "ExposureInuAs",
    "XRayTubeCurrent",
    "ExposureIndex",
    "DeviationIndex",
    "TargetExposureIndex",
    "EntranceDoseInmGy",
    "DetectorType",
    "DetectorID",
    "ViewPosition",
    "GridID",
    "DistanceSourceToDetector",
    "DistanceSourceToPatient",
    "FilterMaterial",
    "BodyPartThickness",
)
for _mod in ("CR", "DX", "RF", "XA"):
    MODALITY_TAGS[_mod] = _XRAY_TAGS


# ---------------------------------------------------------------------------
# Conversão de valores
# ---------------------------------------------------------------------------

def _to_native(value: Any) -> Any:
    """Converte um valor pydicom em algo serializável (JSON/CSV)."""
    if value is None:
        return None

    # MultiValue / listas: converte elemento a elemento
    if isinstance(value, (list, tuple)) or value.__class__.__name__ == "MultiValue":
        return [_to_native(v) for v in value]

    # Sequências DICOM (SQ) não viram coluna de tabela — só o tamanho interessa
    if isinstance(value, Dataset):
        return None

    # DSfloat/IS são subclasses de float/int, mas com repr de string —
    # normaliza para tipos nativos antes de virar CSV/JSON.
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)

    if isinstance(value, bytes):
        return value.hex()[:64]

    # PersonName, UID, DA/TM, DSfloat, IS etc.
    text = str(value).strip()
    return text or None


def _get(ds: "Dataset", keyword: str) -> Any:
    """Lê uma tag pelo keyword, devolvendo None se ausente ou vazia."""
    if keyword not in ds:
        return None
    try:
        return _to_native(ds[keyword].value)
    except Exception:  # tag corrompida não deve derrubar a varredura
        return None


def tags_for_modality(modality: Optional[str]) -> Sequence[str]:
    """Tags específicas da modalidade (vazio se modalidade desconhecida)."""
    if not modality:
        return ()
    return MODALITY_TAGS.get(str(modality).upper(), ())


# ---------------------------------------------------------------------------
# Extração
# ---------------------------------------------------------------------------

def extract_metadata(
    ds: "Dataset",
    file_path: Optional[str] = None,
    extra_tags: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Extrai as tags relevantes de um dataset pydicom.

    Args:
        ds: dataset já lido (`pydicom.dcmread`).
        file_path: caminho do arquivo de origem, incluído no registro.
        extra_tags: keywords adicionais a incluir.

    Returns:
        Dicionário plano (sem sequências aninhadas), pronto para virar
        linha de CSV ou registro JSON.
    """
    record: Dict[str, Any] = {}

    if file_path is not None:
        record["FilePath"] = os.path.abspath(file_path)
        record["FileName"] = os.path.basename(file_path)
        try:
            record["FileSizeBytes"] = os.path.getsize(file_path)
        except OSError:
            record["FileSizeBytes"] = None

    for keyword in COMMON_TAGS:
        record[keyword] = _get(ds, keyword)

    modality = record.get("Modality")
    for keyword in tags_for_modality(modality):
        record[keyword] = _get(ds, keyword)

    for keyword in extra_tags or ():
        record[keyword] = _get(ds, keyword)

    # Informação útil que não é uma tag direta.
    # Nota: a varredura lê os cabeçalhos com stop_before_pixels=True (rápido),
    # então a presença de imagem é inferida por Rows/Columns, não por PixelData.
    record["HasImageData"] = ("Rows" in ds and "Columns" in ds) or "PixelData" in ds
    try:
        record["TransferSyntaxUID"] = str(ds.file_meta.TransferSyntaxUID)
    except Exception:
        record["TransferSyntaxUID"] = None

    return record


def iter_dicom_files(root: str, recursive: bool = True) -> Iterator[str]:
    """Percorre uma pasta devolvendo caminhos de arquivos candidatos a DICOM.

    Não filtra por extensão (arquivos DICOM frequentemente não têm nenhuma);
    a validação real acontece na leitura. Ignora apenas lixo conhecido.
    """
    if os.path.isfile(root):
        yield root
        return

    ignored = {".png", ".jpg", ".jpeg", ".csv", ".json", ".txt", ".md", ".zip", ".pdf"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() in ignored:
                continue
            yield os.path.join(dirpath, name)
        if not recursive:
            break


def scan_folder(
    root: str,
    recursive: bool = True,
    extra_tags: Optional[Iterable[str]] = None,
    verbose: bool = False,
) -> List[Dict[str, Any]]:
    """Varre uma pasta e devolve um registro de metadados por arquivo DICOM.

    Arquivos que não são DICOM válidos são simplesmente ignorados.
    """
    records: List[Dict[str, Any]] = []
    for path in iter_dicom_files(root, recursive=recursive):
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=False)
        except Exception as exc:
            if verbose:
                print(f"  ignorado ({exc.__class__.__name__}): {path}", file=sys.stderr)
            continue
        records.append(extract_metadata(ds, file_path=path, extra_tags=extra_tags))
        if verbose:
            print(f"  lido: {path}", file=sys.stderr)
    return records


def to_dataframe(records: Sequence[Dict[str, Any]]):
    """Converte os registros em DataFrame pandas (import opcional)."""
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "pandas não instalado. Use: pip install pandas"
        ) from exc
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Saída
# ---------------------------------------------------------------------------

def _columns(records: Sequence[Dict[str, Any]]) -> List[str]:
    """União ordenada das colunas (modalidades diferentes têm tags diferentes)."""
    columns: List[str] = []
    seen = set()
    for record in records:
        for key in record:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def _flatten(value: Any) -> Any:
    if isinstance(value, list):
        return "|".join("" if v is None else str(v) for v in value)
    return value


def write_csv(records: Sequence[Dict[str, Any]], output: str) -> None:
    columns = _columns(records)
    with open(output, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({k: _flatten(record.get(k)) for k in columns})


def write_json(records: Sequence[Dict[str, Any]], output: str) -> None:
    with open(output, "w", encoding="utf-8") as fh:
        json.dump(list(records), fh, ensure_ascii=False, indent=2, default=str)


def write_parquet(records: Sequence[Dict[str, Any]], output: str) -> None:
    df = to_dataframe(records)
    # Listas (ex. PixelSpacing) viram string para não complicar o schema
    for column in df.columns:
        if df[column].map(lambda v: isinstance(v, list)).any():
            df[column] = df[column].map(_flatten)
    df.to_parquet(output, index=False)


def write_records(records: Sequence[Dict[str, Any]], output: str) -> None:
    """Grava no formato deduzido pela extensão do arquivo de saída."""
    ext = os.path.splitext(output)[1].lower()
    parent = os.path.dirname(os.path.abspath(output))
    if parent:
        os.makedirs(parent, exist_ok=True)
    if ext == ".csv":
        write_csv(records, output)
    elif ext == ".json":
        write_json(records, output)
    elif ext in (".parquet", ".pq"):
        write_parquet(records, output)
    else:
        raise ValueError(
            f"Extensão de saída não suportada: '{ext}'. Use .csv, .json ou .parquet"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extract_metadata",
        description="Extrai metadados de arquivos DICOM em lote (CSV/JSON/Parquet).",
    )
    parser.add_argument(
        "--input", "-i",
        help="Pasta (varrida recursivamente) ou arquivo DICOM único. "
             "Obrigatório, exceto com --orthanc.",
    )
    parser.add_argument(
        "--output", "-o",
        help="Arquivo de saída: .csv, .json ou .parquet. Sem isto, imprime JSON na tela.",
    )
    parser.add_argument(
        "--no-recursive", action="store_true",
        help="Não entrar em subpastas.",
    )
    parser.add_argument(
        "--tag", action="append", default=[], metavar="KEYWORD",
        help="Tag extra a extrair (keyword DICOM). Pode repetir.",
    )
    parser.add_argument(
        "--orthanc", metavar="URL",
        help="Em vez de ler arquivos, consulta as tags via API REST do Orthanc "
             "(ex.: http://localhost:8042).",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Não mostrar progresso.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.orthanc:
        from .orthanc_client import OrthancClient

        client = OrthancClient(args.orthanc)
        records = client.scan_metadata(extra_tags=args.tag, verbose=not args.quiet)
    else:
        if not args.input:
            print("ERRO: informe --input (pasta/arquivo) ou --orthanc URL.", file=sys.stderr)
            return 2
        if not os.path.exists(args.input):
            print(f"ERRO: caminho não encontrado: {args.input}", file=sys.stderr)
            return 2
        records = scan_folder(
            args.input,
            recursive=not args.no_recursive,
            extra_tags=args.tag,
            verbose=not args.quiet,
        )

    if not records:
        print("Nenhum arquivo DICOM válido encontrado.", file=sys.stderr)
        return 1

    if args.output:
        write_records(records, args.output)
        if not args.quiet:
            studies = {r.get("StudyInstanceUID") for r in records}
            series = {r.get("SeriesInstanceUID") for r in records}
            print(
                f"{len(records)} instância(s), {len(series)} série(s), "
                f"{len(studies)} estudo(s) -> {args.output}"
            )
    else:
        print(json.dumps(records, ensure_ascii=False, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
