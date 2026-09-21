# dicom-viewer

Visualizador DICOM básico em Python: lê um arquivo DICOM, extrai metadados (modalidade, paciente etc.) e exibe a imagem em uma interface gráfica (Tkinter + Matplotlib).

## Objetivo do projeto

- Extrair metadados de imagens DICOM
- Transformar/visualizar imagens DICOM

## Requisitos

- Python 3.8+
- Dependências em `requirements.txt`

```bash
pip install -r requirements.txt
```

## Uso

```bash
python sico.py
```

Isso abre uma janela onde você pode selecionar um arquivo DICOM (`.dcm` ou sem extensão) e visualizar a imagem em escala de cinza, junto com modalidade e nome do paciente extraídos dos metadados.

## Roadmap

Este projeto está evoluindo de visualizador único-arquivo para um miniPACS (Orthanc + OHIF Viewer) com extração de metadados em lote. Veja o plano completo em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

- [ ] Orthanc portátil rodando local (miniPACS)
- [ ] Módulo `metadata/extract_metadata.py` (extração em lote, CLI, CSV/JSON)
- [ ] OHIF Viewer compilado, apontando para o Orthanc local
- [ ] Scripts de automação (`start_all`, `import_folder`)
- [ ] Anonimização automática na importação
- [ ] Thumbnails por série
- [ ] Worklist simulado (didático)

Uso previsto: protótipo de estudo com dados anonimizados/phantoms — sem dados reais de paciente por ora.
