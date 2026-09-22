# dicom-viewer → miniPACS

Protótipo de estudo: um miniPACS local (Orthanc + OHIF Viewer) com extração de
metadados DICOM em lote, anonimização e miniaturas. Roda sem Docker e sem
instalar nada como administrador — inclusive de um pendrive.

**Uso previsto:** dados anonimizados, phantoms e datasets públicos. Sem dados
reais de paciente. Ver `docs/ARQUITETURA.md` para o desenho completo e os
pontos de extensão caso isso mude.

**Guia de comandos (Windows):** [`docs/COMANDOS.md`](docs/COMANDOS.md) — todos
os comandos de linha, com as opções, prontos para copiar.

## Estrutura

```
pacs/           Orthanc portátil — o servidor (DICOM + DICOMweb + storage)
metadata/       extração de metadados, anonimização, miniaturas, cliente REST
viewer-ohif/    configuração do OHIF Viewer apontando para o Orthanc local
viewer_legacy/  sico.py — visualizador de arquivo único (Tkinter)
scripts/        automação: subir tudo, importar pasta, gerar dataset de teste
tests/          testes (não precisam de Orthanc nem de arquivo DICOM externo)
data/           área de trabalho para os exames (não versionada)
```

## Instalação

```bash
pip install -r requirements.txt
```

O binário do Orthanc e o build do OHIF não estão no repositório — ver
`pacs/README.md` e `viewer-ohif/README.md`.

## Começando em 3 comandos

```bash
# 1. Gerar um estudo sintético (CT + MR), sem baixar nada
python scripts/make_phantom_dataset.py --output data/phantom

# 2. Extrair os metadados para uma planilha
python -m metadata.extract_metadata --input data/phantom --output metadata.csv

# 3. Gerar uma miniatura por série
python -m metadata.thumbnails --input data/phantom --output thumbs/
```

Com o Orthanc instalado em `pacs/` (ver `pacs/README.md`):

```bash
./scripts/start_all.sh                                  # Windows: scripts\start_all.bat
python scripts/import_folder.py --input data/phantom
```

Os visualizadores vêm compilados no próprio Orthanc, como plugins — sem Node,
sem `yarn build`:

| | URL |
|---|---|
| Orthanc Explorer | http://localhost:8042 |
| Stone Web Viewer | http://localhost:8042/stone-webviewer/index.html |
| OHIF Viewer | http://localhost:8042/ohif/ |

Detalhes e solução de problemas em `pacs/README.md`.

## O que cada parte faz

### Extração de metadados — `metadata/extract_metadata.py`

Varre uma pasta (ou consulta o Orthanc) e consolida as tags em CSV/JSON/Parquet.
Além do conjunto comum (paciente, estudo, série, equipamento, geometria), traz
as tags de aquisição específicas da modalidade: TR/TE/FA/campo em RM, kVp/mAs/
pitch/kernel em TC, índice de exposição em RX/DX, força de compressão em MG etc.

```bash
python -m metadata.extract_metadata --input data/phantom --output metadata.csv
python -m metadata.extract_metadata --orthanc http://localhost:8042 -o tudo.json
python -m metadata.extract_metadata -i data/ -o m.csv --tag InstitutionalDepartmentName
```

Como biblioteca:

```python
from metadata import scan_folder, to_dataframe

df = to_dataframe(scan_folder("data/phantom"))     # requer pandas
df.groupby(["Modality", "SeriesDescription"]).size()
```

### Anonimização — `metadata/anonymize.py`

Passe os arquivos por aqui **antes** de importar. Pseudonimiza paciente com hash
+ sal, remapeia os UIDs de forma determinística (estudo/série continuam
agrupados, mas não voltam ao original), limpa instituição/médico/datas, remove
tags privadas e overlays, e avisa quando o arquivo declara texto queimado nos
pixels.

```bash
python -m metadata.anonymize -i data/bruto -o data/anonimizado --salt-file .salt
```

O mesmo sal mantém o mesmo pseudônimo entre importações (dá para reencontrar o
mesmo "paciente" em exames diferentes). O arquivo do sal **não é versionado**.

Limite honesto: isto cobre o cabeçalho, não os pixels, e não é um
de-identificador certificado (perfil completo do DICOM PS3.15 E.1).

### Importação — `scripts/import_folder.py`

```bash
python scripts/import_folder.py --input data/anonimizado          # API REST do Orthanc
python scripts/import_folder.py --input data/anonimizado --stow   # DICOMweb STOW-RS
python scripts/import_folder.py --input data/bruto --anonymize --salt-file .salt
```

Com `--anonymize`, a anonimização acontece numa pasta temporária antes do envio:
nada identificável chega ao servidor.

### Miniaturas — `metadata/thumbnails.py`

Uma PNG por série (a imagem do meio), aplicando rescale e a janela do próprio
arquivo; sem janela definida, ajusta por percentis 2–98%.

```bash
python -m metadata.thumbnails --input data/phantom --output thumbs/ --size 256
```

### Dataset de teste — `scripts/make_phantom_dataset.py`

Gera um estudo sintético com duas séries (CT em HU e MR com TR/TE), sem
download e sem nenhum dado de paciente. Serve para exercitar o fluxo inteiro e
é o que os testes usam.

### Visualizador legado — `viewer_legacy/sico.py`

```bash
python viewer_legacy/sico.py
```

Abre um arquivo por vez numa janela Tkinter. Mantido para checagem rápida sem
subir o servidor.

## No Windows: um ajuste depois de clonar

```cmd
git config core.filemode false
```

Os scripts `.sh` são marcados como executáveis no repositório, e o NTFS não
guarda esse bit. Sem o ajuste acima, o git os reporta como modificados logo
depois de um `git reset --hard`, e o `git pull` seguinte aborta com
*"Your local changes would be overwritten by merge"* — mesmo sem ninguém ter
editado nada. O `core.filemode false` vale só para este repositório.

## Testes

```bash
python -m unittest discover -s tests -v
```

25 testes, sem dependência de Orthanc rodando (o cliente é testado contra um
servidor HTTP de mentira) nem de arquivos DICOM externos (gerados na hora).

## Status

- [x] Módulo `metadata/` (extração em lote, CLI, CSV/JSON/Parquet)
- [x] Anonimização com hash + sal e remapeamento determinístico de UIDs
- [x] Cliente REST/DICOMweb do Orthanc (`upload`, STOW-RS, leitura de tags)
- [x] Scripts de automação (`start_all`, `import_folder`)
- [x] Miniaturas por série
- [x] Gerador de dataset sintético + testes
- [x] `orthanc.json` e `ohif-config.js` prontos
- [ ] Orthanc portátil baixado e rodando (passo manual — `pacs/README.md`)
- [x] Stone Web Viewer e OHIF configurados via plugin (`orthanc.json`), sem Node
- [ ] Build próprio do OHIF (opcional, só para customizar — `viewer-ohif/README.md`)
- [ ] Worklist simulado (config já preparada, desligada por padrão)

Plano completo e decisões de arquitetura: [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).
