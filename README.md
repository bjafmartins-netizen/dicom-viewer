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

- [ ] Extração e exibição completa de metadados (tags DICOM) em painel dedicado
- [ ] Suporte a séries/múltiplos arquivos (não só imagem única)
- [ ] Exportação de imagem (PNG/JPEG) e de metadados (CSV/JSON)
- [ ] Anonimização de dados do paciente
