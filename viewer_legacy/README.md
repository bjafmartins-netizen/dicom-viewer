# viewer_legacy

Visualizador standalone original (`sico.py`): abre **um** arquivo DICOM por vez
numa janela Tkinter. Mantido intacto para checagem rápida de um arquivo solto,
sem precisar subir o Orthanc.

```bash
python viewer_legacy/sico.py
```

Para trabalhar com pastas/estudos inteiros, use `metadata/` (metadados em lote)
e o OHIF apontando para o Orthanc (ver `docs/ARQUITETURA.md`).
