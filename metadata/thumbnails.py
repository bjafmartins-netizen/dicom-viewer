"""Geração de miniaturas (PNG) a partir de arquivos DICOM.

Uma miniatura por série (a imagem do meio, que costuma ser a mais
representativa) permite navegar um dataset inteiro no explorador de arquivos,
sem abrir o viewer completo.

Usa pydicom + numpy + Pillow. Não usa matplotlib: aqui não há janela nem eixo,
só conversão de pixels — Pillow é mais leve e mais rápido para isso.

    python -m metadata.thumbnails --input exames/ --output thumbs/
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import numpy as np
    import pydicom
except ImportError:  # pragma: no cover
    print("ERRO: 'pydicom' e/ou 'numpy' não encontrados. pip install -r requirements.txt")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print("ERRO: 'Pillow' não encontrado. pip install -r requirements.txt")
    sys.exit(1)

from .extract_metadata import iter_dicom_files

# pydicom 3.x moveu os helpers de LUT para pydicom.pixels
try:
    from pydicom.pixels import apply_modality_lut, apply_voi_lut
except ImportError:  # pydicom 2.x
    from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut


def to_display_array(ds: "pydicom.Dataset") -> "np.ndarray":
    """Converte o pixel data em uma matriz 8 bits pronta para exibição.

    Aplica Modality LUT (rescale slope/intercept → unidades reais, ex. HU) e a
    VOI LUT / janela do próprio arquivo quando existe; sem janela, faz um
    ajuste por percentis (2–98%), que evita que um outlier estoure o contraste.
    """
    array = ds.pixel_array

    # Multiframe: pega o quadro do meio
    if array.ndim == 3 and getattr(ds, "SamplesPerPixel", 1) == 1:
        array = array[array.shape[0] // 2]

    array = apply_modality_lut(array, ds)

    if "WindowCenter" in ds and "WindowWidth" in ds:
        try:
            array = apply_voi_lut(array, ds)
        except Exception:
            pass

    array = np.asarray(array, dtype=np.float64)

    if array.ndim == 3:  # RGB (ex. US, captura secundária)
        array = array.astype(np.uint8)
        return array

    low, high = np.percentile(array, (2.0, 98.0))
    if high <= low:
        low, high = float(array.min()), float(array.max())
    if high <= low:
        return np.zeros(array.shape, dtype=np.uint8)

    array = np.clip((array - low) / (high - low), 0.0, 1.0)

    if str(getattr(ds, "PhotometricInterpretation", "")).upper() == "MONOCHROME1":
        array = 1.0 - array  # MONOCHROME1: valor alto = preto

    return (array * 255.0).astype(np.uint8)


def make_thumbnail(ds: "pydicom.Dataset", size: int = 256) -> "Image.Image":
    """Miniatura quadrada (mantendo a proporção) de um dataset."""
    array = to_display_array(ds)
    image = Image.fromarray(array)
    image.thumbnail((size, size))
    return image


def _series_key(ds: "pydicom.Dataset") -> str:
    return str(getattr(ds, "SeriesInstanceUID", "") or "sem-serie")


def _safe_name(*parts: Any) -> str:
    raw = "_".join(str(p) for p in parts if p not in (None, ""))
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in raw)[:120]


def thumbnails_for_folder(
    input_dir: str,
    output_dir: str,
    size: int = 256,
    per_instance: bool = False,
    recursive: bool = True,
    verbose: bool = True,
) -> List[str]:
    """Gera miniaturas de uma pasta. Por padrão, uma por série.

    Returns:
        Lista de PNGs gerados.
    """
    os.makedirs(output_dir, exist_ok=True)
    generated: List[str] = []

    if per_instance:
        for path in iter_dicom_files(input_dir, recursive=recursive):
            ds = _read(path)
            if ds is None:
                continue
            name = _safe_name(
                getattr(ds, "Modality", "XX"),
                getattr(ds, "SeriesNumber", ""),
                getattr(ds, "InstanceNumber", ""),
                os.path.basename(path),
            ) + ".png"
            saved = _save(ds, os.path.join(output_dir, name), size, verbose)
            if saved:
                generated.append(saved)
        return generated

    # Uma por série: agrupa primeiro, depois escolhe a imagem do meio
    series: Dict[str, List[Tuple[int, str]]] = {}
    info: Dict[str, "pydicom.Dataset"] = {}
    for path in iter_dicom_files(input_dir, recursive=recursive):
        header = _read(path, stop_before_pixels=True)
        if header is None or "PixelData" not in header and not _likely_image(header):
            continue
        key = _series_key(header)
        try:
            order = int(getattr(header, "InstanceNumber", 0) or 0)
        except (TypeError, ValueError):
            order = 0
        series.setdefault(key, []).append((order, path))
        info.setdefault(key, header)

    for key, entries in series.items():
        entries.sort()
        _, middle_path = entries[len(entries) // 2]
        ds = _read(middle_path)
        if ds is None:
            continue
        header = info[key]
        name = _safe_name(
            getattr(header, "Modality", "XX"),
            f"s{getattr(header, 'SeriesNumber', '') or 0}",
            getattr(header, "SeriesDescription", "") or key[-8:],
        ) + ".png"
        saved = _save(ds, os.path.join(output_dir, name), size, verbose)
        if saved:
            generated.append(saved)

    return generated


def _likely_image(ds: "pydicom.Dataset") -> bool:
    return "Rows" in ds and "Columns" in ds


def _read(path: str, stop_before_pixels: bool = False) -> Optional["pydicom.Dataset"]:
    try:
        return pydicom.dcmread(path, stop_before_pixels=stop_before_pixels)
    except Exception:
        return None


def _save(ds: "pydicom.Dataset", destination: str, size: int, verbose: bool) -> Optional[str]:
    try:
        image = make_thumbnail(ds, size=size)
    except Exception as exc:
        if verbose:
            print(f"  sem miniatura ({exc.__class__.__name__}): {destination}", file=sys.stderr)
        return None
    image.save(destination)
    if verbose:
        print(f"  {destination}")
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thumbnails",
        description="Gera miniaturas PNG de exames DICOM (uma por série por padrão).",
    )
    parser.add_argument("--input", "-i", required=True, help="Pasta com os DICOM.")
    parser.add_argument("--output", "-o", required=True, help="Pasta de destino dos PNG.")
    parser.add_argument("--size", type=int, default=256, help="Lado maior em pixels (padrão 256).")
    parser.add_argument(
        "--per-instance", action="store_true",
        help="Uma miniatura por arquivo, em vez de uma por série.",
    )
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument("--quiet", "-q", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not os.path.exists(args.input):
        print(f"ERRO: caminho não encontrado: {args.input}", file=sys.stderr)
        return 2
    generated = thumbnails_for_folder(
        args.input,
        args.output,
        size=args.size,
        per_instance=args.per_instance,
        recursive=not args.no_recursive,
        verbose=not args.quiet,
    )
    print(f"{len(generated)} miniatura(s) em {args.output}")
    return 0 if generated else 1


if __name__ == "__main__":
    raise SystemExit(main())
