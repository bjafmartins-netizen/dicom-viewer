"""Módulo de metadados do miniPACS.

Separa a leitura/extração de metadados DICOM da interface gráfica (que ficou em
`viewer_legacy/sico.py`), conforme docs/ARQUITETURA.md.

Submódulos:
    extract_metadata — extração em lote (CSV/JSON/Parquet/DataFrame)
    anonymize        — anonimização de cabeçalho antes da importação
    orthanc_client   — cliente REST/DICOMweb do Orthanc
    thumbnails       — miniaturas PNG por série

Os nomes mais usados são reexportados aqui:

    from metadata import scan_folder, extract_metadata

Os imports são preguiçosos (PEP 562) para que `python -m metadata.extract_metadata`
não reimporte o submódulo durante a carga do pacote.
"""

from typing import Any

__version__ = "0.2.0"

_EXPORTS = {
    "COMMON_TAGS": "extract_metadata",
    "MODALITY_TAGS": "extract_metadata",
    "extract_metadata": "extract_metadata",
    "iter_dicom_files": "extract_metadata",
    "scan_folder": "extract_metadata",
    "to_dataframe": "extract_metadata",
    "write_records": "extract_metadata",
    "anonymize_dataset": "anonymize",
    "anonymize_folder": "anonymize",
    "OrthancClient": "orthanc_client",
    "make_thumbnail": "thumbnails",
    "thumbnails_for_folder": "thumbnails",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'metadata' has no attribute '{name}'")
    import importlib

    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))
