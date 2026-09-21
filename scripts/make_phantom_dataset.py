#!/usr/bin/env python3
"""Gera um dataset DICOM sintético (phantom) para testar o miniPACS.

Motivo: dá para exercitar importação, extração de metadados, anonimização,
miniaturas e o viewer sem depender de download nem de nenhum arquivo real.
As imagens são geradas matematicamente (círculos/elipses), não são de paciente.

    python scripts/make_phantom_dataset.py --output data/phantom
    python scripts/make_phantom_dataset.py --output data/phantom --slices 20

Gera duas séries num mesmo estudo: uma CT (em HU) e uma MR (com TR/TE).
Para dados públicos reais e anonimizados, veja pacs/README.md (TCIA e os
exemplos oficiais do Orthanc).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence

try:
    import numpy as np
    import pydicom
    from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, MRImageStorage, generate_uid
except ImportError:
    print("ERRO: 'pydicom' e/ou 'numpy' não encontrados. pip install -r requirements.txt")
    sys.exit(1)


def _phantom(size: int, slice_index: int, n_slices: int) -> "np.ndarray":
    """Elipse com estruturas internas; o conteúdo varia ao longo do eixo Z."""
    yy, xx = np.mgrid[0:size, 0:size]
    cy = cx = size / 2.0
    # o "corpo" afina nas extremidades da pilha
    taper = 0.55 + 0.35 * np.sin(np.pi * (slice_index + 0.5) / n_slices)
    body = (((xx - cx) / (0.45 * size)) ** 2 + ((yy - cy) / (taper * size)) ** 2) <= 1.0

    image = np.zeros((size, size), dtype=np.float32)
    image[body] = 40.0  # tecido mole

    # duas estruturas internas com densidades diferentes
    for dx, dy, radius, value in (
        (-0.15, -0.05, 0.10, -850.0),   # ar/pulmão
        (0.17, 0.02, 0.09, 120.0),      # estrutura densa
        (0.0, 0.22, 0.06, 1100.0),      # osso
    ):
        mask = ((xx - (cx + dx * size)) ** 2 + (yy - (cy + dy * size)) ** 2) <= (radius * size) ** 2
        image[mask & body] = value

    image[~body] = -1000.0  # ar fora do corpo
    rng = np.random.default_rng(1000 + slice_index)
    image += rng.normal(0.0, 8.0, image.shape).astype(np.float32)
    return image


def _base_dataset(
    sop_class_uid: str,
    study_uid: str,
    series_uid: str,
    patient_id: str,
    patient_name: str,
) -> "FileDataset":
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class_uid
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationVersionName = "DCMVIEW-PHANTOM"

    ds = FileDataset("", {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop_class_uid
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid

    ds.PatientID = patient_id
    ds.PatientName = patient_name
    ds.PatientSex = "O"
    ds.PatientBirthDate = "19800101"
    ds.StudyDate = "20240115"
    ds.StudyTime = "101500"
    ds.SeriesDate = ds.StudyDate
    ds.SeriesTime = ds.StudyTime
    ds.AccessionNumber = "ACC-PHANTOM-001"
    ds.StudyID = "1"
    ds.StudyDescription = "PHANTOM SINTETICO - TESTE"
    ds.InstitutionName = "LAB DE TESTES"
    ds.ReferringPhysicianName = "TESTE^MEDICO"
    ds.PatientIdentityRemoved = "NO"
    ds.BurnedInAnnotation = "NO"
    ds.Manufacturer = "dicom-viewer"
    ds.ManufacturerModelName = "phantom-generator"
    ds.StationName = "ESTACAO-TESTE"
    ds.SoftwareVersions = "0.2.0"
    ds.SpecificCharacterSet = "ISO_IR 100"
    return ds


def _write_pixels(ds: "FileDataset", array: "np.ndarray", intercept: float, slope: float) -> None:
    stored = np.clip((array - intercept) / slope, 0, 65535).astype(np.uint16)
    ds.Rows, ds.Columns = stored.shape
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.RescaleIntercept = intercept
    ds.RescaleSlope = slope
    ds.PixelData = stored.tobytes()


def make_ct_series(output_dir: str, n_slices: int, size: int, study_uid: str,
                   patient_id: str, patient_name: str) -> int:
    series_uid = generate_uid()
    frame_uid = generate_uid()
    thickness = 3.0
    for index in range(n_slices):
        ds = _base_dataset(CTImageStorage, study_uid, series_uid, patient_id, patient_name)
        ds.Modality = "CT"
        ds.SeriesNumber = 1
        ds.SeriesDescription = "CT AXIAL PHANTOM"
        ds.ProtocolName = "PHANTOM/CT/AXIAL"
        ds.BodyPartExamined = "CHEST"
        ds.InstanceNumber = index + 1
        ds.ImageType = ["ORIGINAL", "PRIMARY", "AXIAL"]
        ds.PatientPosition = "HFS"
        ds.FrameOfReferenceUID = frame_uid
        ds.PixelSpacing = [0.7, 0.7]
        ds.SliceThickness = thickness
        ds.SpacingBetweenSlices = thickness
        ds.SliceLocation = round(index * thickness, 2)
        ds.ImagePositionPatient = [-89.6, -89.6, round(index * thickness, 2)]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.WindowCenter = 40
        ds.WindowWidth = 400
        # parâmetros de aquisição (exercitam MODALITY_TAGS["CT"])
        ds.KVP = 120
        ds.XRayTubeCurrent = 180
        ds.ExposureTime = 500
        ds.Exposure = 90
        ds.ConvolutionKernel = "B30f"
        ds.SpiralPitchFactor = 0.9
        ds.TotalCollimationWidth = 38.4
        ds.SingleCollimationWidth = 0.6
        ds.ReconstructionDiameter = 358.4
        ds.GantryDetectorTilt = 0.0
        ds.FilterType = "BODY"

        _write_pixels(ds, _phantom(size, index, n_slices), intercept=-1024.0, slope=1.0)
        path = os.path.join(output_dir, "CT", f"CT_{index + 1:04d}.dcm")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ds.save_as(path, enforce_file_format=True)
    return n_slices


def make_mr_series(output_dir: str, n_slices: int, size: int, study_uid: str,
                   patient_id: str, patient_name: str) -> int:
    series_uid = generate_uid()
    frame_uid = generate_uid()
    thickness = 5.0
    for index in range(n_slices):
        ds = _base_dataset(MRImageStorage, study_uid, series_uid, patient_id, patient_name)
        ds.Modality = "MR"
        ds.SeriesNumber = 2
        ds.SeriesDescription = "MR T2 TSE PHANTOM"
        ds.ProtocolName = "PHANTOM/MR/T2_TSE"
        ds.BodyPartExamined = "BRAIN"
        ds.InstanceNumber = index + 1
        ds.ImageType = ["ORIGINAL", "PRIMARY", "M", "NORM"]
        ds.PatientPosition = "HFS"
        ds.FrameOfReferenceUID = frame_uid
        ds.PixelSpacing = [0.5, 0.5]
        ds.SliceThickness = thickness
        ds.SpacingBetweenSlices = thickness + 0.5
        ds.SliceLocation = round(index * thickness, 2)
        ds.ImagePositionPatient = [-64.0, -64.0, round(index * thickness, 2)]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        # parâmetros de aquisição (exercitam MODALITY_TAGS["MR"])
        ds.MagneticFieldStrength = 1.5
        ds.ScanningSequence = "SE"
        ds.SequenceVariant = ["SK", "SP"]
        ds.MRAcquisitionType = "2D"
        ds.SequenceName = "tse2d1_15"
        ds.RepetitionTime = 4500.0
        ds.EchoTime = 96.0
        ds.EchoTrainLength = 15
        ds.FlipAngle = 150.0
        ds.NumberOfAverages = 1.0
        ds.PixelBandwidth = 200
        ds.InPlanePhaseEncodingDirection = "ROW"
        ds.ReceiveCoilName = "HEAD_16"

        image = np.clip(_phantom(size, index, n_slices) + 1000.0, 0, None) * 0.5
        _write_pixels(ds, image, intercept=0.0, slope=1.0)
        path = os.path.join(output_dir, "MR", f"MR_{index + 1:04d}.dcm")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ds.save_as(path, enforce_file_format=True)
    return n_slices


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="make_phantom_dataset",
        description="Gera um estudo DICOM sintético (CT + MR) para testes.",
    )
    parser.add_argument("--output", "-o", default="data/phantom", help="Pasta de destino.")
    parser.add_argument("--slices", type=int, default=10, help="Cortes por série (padrão 10).")
    parser.add_argument("--size", type=int, default=256, help="Matriz da imagem (padrão 256).")
    parser.add_argument("--patient-id", default="PHANTOM001")
    parser.add_argument("--patient-name", default="PHANTOM^TESTE")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    os.makedirs(args.output, exist_ok=True)
    study_uid = generate_uid()

    total = make_ct_series(args.output, args.slices, args.size, study_uid,
                           args.patient_id, args.patient_name)
    total += make_mr_series(args.output, args.slices, args.size, study_uid,
                            args.patient_id, args.patient_name)

    print(f"{total} arquivo(s) DICOM sintético(s) gerados em {args.output}")
    print("Próximo passo sugerido:")
    print(f"  python -m metadata.extract_metadata --input {args.output} --output metadata.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
