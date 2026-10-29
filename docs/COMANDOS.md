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

### De um exame inteiro (ou de vários)

Aponte para a pasta que contém o exame — ou a que contém vários exames. A
varredura entra nas subpastas sozinha e sai tudo num CSV só, com
`StudyInstanceUID` e `SeriesInstanceUID` separando o que é de cada um:

```cmd
python -m metadata.extract_metadata --input D:\exames --output metadados.csv
```

`--no-recursive` limita à pasta indicada, sem subpastas.

### Uma linha por série (em vez de uma por imagem)

Por padrão sai uma linha por imagem, então um exame de 300 cortes vira 300
linhas. Para revisar protocolo, use `--nivel serie`:

```cmd
python -m metadata.extract_metadata --input D:\exames --output series.csv --nivel serie
```

Cada linha é uma série, com as colunas do protocolo e da aquisição, mais:

| Coluna | Conteúdo |
|---|---|
| `InstanceCount` | quantas imagens a série tem |
| `SliceLocationMin` / `SliceLocationMax` | faixa coberta pelos cortes |
| `ImagePlane` | AXIAL, CORONAL, SAGITAL ou OBLIQUO (deduzido da orientação) |
| `InPlaneResolutionMM` | resolução no plano, ex. `0.5x0.5` |
| `MatrixRowsColumns` | matriz da imagem, ex. `256x256` |

As colunas que só fazem sentido por imagem (`SOPInstanceUID`,
`InstanceNumber`, `SliceLocation`, `FilePath`) não aparecem. Quando um valor
**muda dentro da série** — dois kernels de reconstrução, por exemplo — a
célula mostra os dois (`B30f | B70f`) em vez de escolher um escondido.

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

### Tags privadas de fabricante (Siemens, GE, Philips)

Tag sem nome no padrão DICOM se pede pelo número, no formato `grupo,elemento`:

```cmd
python -m metadata.extract_metadata --input D:\exames --output m.csv --tag 0021,1004
```

Aceita `0021,1004`, `(0021,1004)` ou `0x0021,0x1004`. A coluna sai com o nome
que você escreveu. Para descobrir quais tags privadas o seu equipamento grava,
abra um exame dele no Orthanc Explorer e veja a lista de tags da instância —
as privadas aparecem como "Unknown Tag & Data", com o `PrivateCreator` do
fabricante ao lado.

Funciona tanto por arquivo quanto por `--orthanc`.

### Outros formatos

```cmd
python -m metadata.extract_metadata --input data\phantom --output metadados.json
python -m metadata.extract_metadata --input data\phantom --output metadados.parquet
```

---

## 6. Conferir protocolo de esclerose múltipla

Verifica se um exame de RM tem as sequências mínimas para aplicar os critérios
de McDonald 2024:

```cmd
python scripts\check_ms_protocol.py --study 1.3.12.2.1107.5.8.15.131195.3000002609
```

| Opção | Efeito |
|---|---|
| `--study ID` | um estudo: aceita o StudyInstanceUID ou o ID do Orthanc |
| `--todos` | avalia todos os estudos do servidor |
| `--input pasta` | lê os arquivos direto da pasta, sem o Orthanc |

O que ele decide:

- **Bloqueia** quando falta FLAIR 3D ou T1 pós-contraste.
- **Só alerta** quando falta SWI/T2* — o exame segue, mas sem o Sinal da Veia
  Central.
- Informa se há cobertura do nervo óptico.

Reconhece a sequência pela descrição e pelo nome do protocolo, com as marcas
dos fabricantes (SPACE, CUBE, VISTA, MPRAGE). Quando o nome não diz que é
volumétrica, confere `MRAcquisitionType` no cabeçalho.

Código de saída: `0` viável, `1` bloqueado, `2` erro de uso — dá para usar em
automação.

---

## 7. Miniaturas (PNG)

Uma imagem por série (o corte do meio), com a janela do próprio arquivo:

```cmd
python -m metadata.thumbnails --input data\phantom --output thumbs
```

| Opção | Efeito |
|---|---|
| `--size 512` | lado maior em pixels (padrão 256) |
| `--per-instance` | uma miniatura por arquivo, em vez de uma por série |

---

## 8. Visualizador legado (um arquivo, sem servidor)

```cmd
python viewer_legacy\sico.py
```

Abre uma janela para escolher e ver um arquivo DICOM por vez.

---

## 9. Testes

```cmd
python -m unittest discover -s tests -v
```

Não precisam do Orthanc rodando nem de exames externos.

---

## 10. Git (manter igual ao GitHub)

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
