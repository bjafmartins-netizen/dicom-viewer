# Guia de comandos

Referência rápida de todos os comandos do projeto, no formato do Windows
(`cmd`). Para o que cada parte faz e por quê, ver o [`README.md`](../README.md).

## Antes de tudo: abrir o terminal certo

1. Abra o **WinPython Command Prompt** (`E:\winPY\WinPython Command Prompt.exe`).
   Nele, `python` já é o Python do WinPython, com pydicom, numpy, pillow e
   pandas instalados.
2. Entre na pasta do projeto — os comandos `python -m metadata...` só
   funcionam a partir dela:

```cmd
cd /d E:\DICOM\dicom-viewer
```

> Num `cmd` ou PowerShell comum, `python` abre a Microsoft Store em vez de
> rodar. Nesse caso, troque `python` por `E:\winPY\python\python.exe` em
> todos os comandos abaixo.

Todo comando aceita `--help` para listar as opções:

```cmd
python -m metadata.extract_metadata --help
```

---

## 1. Servidor (Orthanc)

### Subir

Dois cliques em `scripts\start_all.bat`, ou:

```cmd
scripts\start_all.bat
```

Abre a janela **"Orthanc (miniPACS)"** (deixe aberta) e o Stone Web Viewer no
navegador. Para encerrar, feche essa janela.

| | Endereço |
|---|---|
| Orthanc Explorer (lista, upload, download) | http://localhost:8042 |
| Stone Web Viewer | http://localhost:8042/stone-webviewer/index.html |
| OHIF Viewer | http://localhost:8042/ohif/ |

### Subir vendo o log inteiro

Útil quando o servidor não sobe — o log fica em `pacs\orthanc.log`:

```cmd
cd pacs
Orthanc.exe orthanc.json > orthanc.log 2>&1
```

Sucesso = três linhas `Registering plugin` (dicom-web, stone-webviewer, ohif)
e nenhum `Uncaught exception`.

### Conferir se está no ar

```cmd
curl http://localhost:8042/system
curl http://localhost:8042/statistics
curl http://localhost:8042/dicom-web/studies
```

### "Port already in use (port = 4242)"

Alguém já ocupa a porta — em geral outro Orthanc aberto:

```cmd
netstat -ano | findstr ":4242 :8042"
taskkill /PID <numero_do_PID> /F
```

O serviço Orthanc do Windows já foi desativado; se um dia voltar, num terminal
**como administrador** (no PowerShell, escreva `sc.exe` — `sc` sozinho é
outro comando):

```cmd
sc.exe query Orthanc
sc.exe stop Orthanc
sc.exe config Orthanc start= disabled
```

---

## 2. Gerar dados de teste (phantom sintético)

Estudo com duas séries (CT e MR), sem nenhum dado de paciente:

```cmd
python scripts\make_phantom_dataset.py --output data\phantom
```

| Opção | Efeito |
|---|---|
| `--slices 20` | cortes por série (padrão 10) |
| `--size 512` | matriz da imagem (padrão 256) |
| `--patient-id X --patient-name "SOBRENOME^NOME"` | identificação do phantom |

---

## 3. Anonimizar

Sempre **antes** de importar exames novos. Cria cópias anonimizadas; os
originais não são alterados.

```cmd
python -m metadata.anonymize --input data\bruto --output data\anonimizado --salt-file .salt
```

| Opção | Efeito |
|---|---|
| `--salt-file .salt` | guarda o sal em arquivo; o mesmo arquivo mantém o mesmo pseudônimo entre importações. **Não versione** (o `.gitignore` já ignora) |
| `--date-policy year` | datas: mantém só o ano (padrão). Outras: `remove`, `shift` (com `--shift-days N`), `keep` |
| `--keep-uids` | não remapeia os UIDs |
| `--dry-run` | só simula, não grava nada |

Cobre o cabeçalho, não os pixels: o script avisa quando o arquivo declara texto
gravado na imagem (`BurnedInAnnotation`).

---

## 4. Importar exames para o servidor

```cmd
python scripts\import_folder.py --input data\anonimizado
```

| Opção | Efeito |
|---|---|
| `--anonymize --salt-file .salt` | anonimiza numa pasta temporária antes de enviar — nada identificável chega ao servidor |
| `--keep-anonymized pasta` | guarda a cópia anonimizada em vez de descartar |
| `--stow` | envia por DICOMweb (STOW-RS) em vez da API REST do Orthanc |
| `--no-recursive` | não entra em subpastas |
| `--url http://127.0.0.1:8042` | outro servidor (padrão: o local) |

Exemplo — importar exames novos já anonimizando:

```cmd
python scripts\import_folder.py --input D:\exames_novos --anonymize --salt-file .salt
```

---

## 5. Exportar metadados (CSV, JSON, Parquet)

O formato sai da extensão do arquivo em `--output`. Sem `--output`, o
resultado aparece na tela em JSON. Uma linha por imagem, uma coluna por tag.

### De uma imagem só

```cmd
python -m metadata.extract_metadata --input data\phantom\CT\CT_0001.dcm --output metadados_CT_0001.csv
```

### De uma série, estudo ou pasta inteira

```cmd
python -m metadata.extract_metadata --input data\phantom --output metadados.csv
```

`--no-recursive` limita à pasta indicada, sem subpastas.

### De tudo o que está no servidor

```cmd
python -m metadata.extract_metadata --orthanc http://localhost:8042 --output metadados_servidor.csv
```

Sempre exporta o servidor inteiro. Para uma imagem que só está no Orthanc:
abra o Orthanc Explorer → paciente → estudo → série → instância →
**Download DICOM file**, e use o comando "de uma imagem só" no arquivo baixado.

### Tags extras

Além do conjunto padrão (paciente, estudo, série, equipamento, geometria e
parâmetros de aquisição da modalidade), acrescente qualquer tag pelo nome
DICOM — uma `--tag` para cada:

```cmd
python -m metadata.extract_metadata --input data\phantom --output m.csv --tag BodyPartExamined --tag ContrastBolusAgent
```

### Outros formatos

```cmd
python -m metadata.extract_metadata --input data\phantom --output metadados.json
python -m metadata.extract_metadata --input data\phantom --output metadados.parquet
```

---

## 6. Miniaturas (PNG)

Uma imagem por série (o corte do meio), com a janela do próprio arquivo:

```cmd
python -m metadata.thumbnails --input data\phantom --output thumbs
```

| Opção | Efeito |
|---|---|
| `--size 512` | lado maior em pixels (padrão 256) |
| `--per-instance` | uma miniatura por arquivo, em vez de uma por série |

---

## 7. Visualizador legado (um arquivo, sem servidor)

```cmd
python viewer_legacy\sico.py
```

Abre uma janela para escolher e ver um arquivo DICOM por vez.

---

## 8. Testes

```cmd
python -m unittest discover -s tests -v
```

Não precisam do Orthanc rodando nem de exames externos.

---

## 9. Git (manter igual ao GitHub)

```cmd
git status
git pull
```

Depois de clonar o repositório no Windows, rode uma vez — senão o `git pull`
aborta dizendo que há mudanças locais que ninguém fez:

```cmd
git config core.filemode false
```

---

## Fluxo típico com exames novos

```cmd
cd /d E:\DICOM\dicom-viewer
scripts\start_all.bat
python scripts\import_folder.py --input D:\exames_novos --anonymize --salt-file .salt
python -m metadata.extract_metadata --orthanc http://localhost:8042 --output metadados.csv
```

Depois, abra os exames no Stone ou no OHIF pelos endereços da seção 1.
