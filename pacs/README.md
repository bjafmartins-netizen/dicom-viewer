# pacs/ — Orthanc portátil (o miniPACS)

O Orthanc é o servidor: recebe, guarda e indexa os exames, e já fala DICOMweb
nativamente — é nele que o OHIF se conecta. O binário **não está versionado**
neste repositório (é grande e específico de plataforma); baixe uma vez e
coloque aqui dentro.

## 1. Baixar (Windows, sem instalar, sem admin)

1. Acesse https://www.orthanc-server.com/download-windows.php
2. Baixe a versão **portátil / ZIP** (não o instalador `.msi`).
3. Extraia o conteúdo dentro desta pasta, de modo a ficar assim:

```
pacs/
├── Orthanc.exe
├── plugins/                 <- DLLs dos plugins (inclui o DICOMweb)
├── orthanc.json             <- config versionada (já está no repositório)
└── orthanc-db/              <- criado sozinho na 1ª execução (não versionado)
```

Confirme que o plugin DICOMweb (`OrthancDicomWeb.dll`) está em `plugins/` —
sem ele o OHIF não conecta.

No Linux, o equivalente é o pacote `orthanc` + `orthanc-dicomweb` da
distribuição (ou o tarball oficial); a mesma `orthanc.json` serve.

## 2. Rodar

```cmd
cd pacs
Orthanc.exe orthanc.json
```

Ou, da raiz do projeto, use o script que sobe tudo junto:
`scripts\start_all.bat` (Windows) / `scripts/start_all.sh` (Linux/Mac).

Endereços:

| O quê | URL |
|---|---|
| Orthanc Explorer (interface web própria) | http://localhost:8042 |
| API REST | http://localhost:8042/system |
| DICOMweb (é o que o OHIF consome) | http://localhost:8042/dicom-web |
| Porta DICOM (C-STORE, AET `MINIPACS`) | 4242 |
| Stone Web Viewer | http://localhost:8042/stone-webviewer/index.html |
| OHIF Viewer (plugin) | http://localhost:8042/ohif/ |

Teste rápido de que subiu:

```bash
curl http://localhost:8042/system
```

## 3. Importar exames

- **Manual:** arrastar arquivos na aba *Upload* do Orthanc Explorer.
- **Em lote:** `python scripts/import_folder.py --input data/anonimizado`
- **Anonimizar antes** (recomendado, é a política do projeto):
  `python -m metadata.anonymize -i data/bruto -o data/anonimizado --salt-file .salt`

## 4. Dados de teste

Sem baixar nada:

```bash
python scripts/make_phantom_dataset.py --output data/phantom
```

Gera um estudo sintético (uma série CT em HU e uma série MR com TR/TE), útil
para exercitar todo o fluxo. Para dados reais, públicos e já anonimizados:

- **TCIA** — https://www.cancerimagingarchive.net (requer o NBIA Data Retriever)
- **Imagens de exemplo do Orthanc** — https://orthanc.uclouvain.be/book/faq/sample-images.html

## Visualizadores: Stone e OHIF, sem compilar nada

O instalador do Orthanc para Windows **já traz os dois visualizadores
compilados** em `pacs/plugins/`:

| Plugin (Windows 64 bits) | Viewer | URL |
|---|---|---|
| `libStoneWebViewer-Windows64.dll` | Stone Web Viewer | http://localhost:8042/stone-webviewer/index.html |
| `libOrthancOHIF-Windows64.dll` | OHIF Viewer | http://localhost:8042/ohif/ |
| `OrthancDicomWeb.dll` | (fonte de dados dos dois) | http://localhost:8042/dicom-web |

Ou seja: **não é preciso Node nem `yarn build`** para ter o OHIF. Compilar do
zero (ver `viewer-ohif/README.md`) só faz sentido se você quiser modificar o
OHIF ou usar extensões que não vêm no plugin.

No Linux os mesmos plugins se chamam `libStoneWebViewer.so`,
`libOrthancOHIF.so` e `libOrthancDicomWeb.so`.

### A chave `Plugins` é uma lista explícita

O instalador coloca uns 30 plugins na pasta (MySQL, PostgreSQL, AWS, Azure,
WSI...). Carregar todos só gera ruído no log, então `orthanc.json` lista
apenas os três acima. Para ver o que existe na sua instalação:

```cmd
dir pacs\plugins
```

Se algum nome for diferente do que está no `orthanc.json` (muda entre
versões), ajuste a lista — ou troque tudo por `"Plugins": ["./plugins"]` para
carregar a pasta inteira.

Confira no log da janela do Orthanc, na inicialização, as linhas que começam
com `Registering plugin`: os três devem aparecer.

### Instalador x ZIP portátil

Se você usou o **instalador** (`.exe`, com `unins000.exe` na pasta), ele traz
um `orthanc.json` próprio em `pacs/Configuration/`. Isso não atrapalha: o
`start_all` chama `Orthanc.exe orthanc.json`, passando explicitamente o nosso
arquivo, e o Orthanc ignora os demais.

O que **não** funciona é ter o Orthanc instalado como serviço do Windows
rodando ao mesmo tempo: ele ocupa a porta 8042 e você vai ver uma config que
não é a nossa. Se acontecer, pare o serviço em `services.msc` (nome
*Orthanc*) antes de rodar o `start_all`.

### Se o Orthanc morrer na inicialização

```
Uncaught exception, stopping now: The TCP port of the DICOM server is
privileged or already in use (port = 4242)
```

Alguém já está com a porta. Em geral é o Orthanc instalado como **serviço do
Windows**, que sobe junto com a máquina:

```cmd
sc query Orthanc
netstat -ano | findstr ":4242"
```

Se o serviço estiver `RUNNING`, pare-o (terminal como administrador):

```cmd
sc stop Orthanc
sc config Orthanc start= disabled
```

Se o `netstat` apontar um `Orthanc.exe` órfão de uma tentativa anterior, mate
pelo PID: `taskkill /PID <numero> /F`.

Para ver o log inteiro em vez da janela separada que o `start_all` abre, rode
o servidor direto e capture a saída:

```cmd
cd pacs
Orthanc.exe orthanc.json > orthanc.log 2>&1
```

### Se o viewer não abrir

1. O plugin apareceu no log? Sem a linha `Registering plugin`, o nome do
   arquivo na chave `Plugins` está errado.
2. O DICOMweb responde? `curl http://localhost:8042/dicom-web/studies` —
   os dois viewers leem as imagens por ele.
3. Reiniciou o Orthanc depois de mexer na config? Ele só lê na inicialização.

## Configuração

`orthanc.json` está comentado internamente (as chaves começadas por `//` são
ignoradas pelo Orthanc). Padrões escolhidos aqui:

- **Autenticação desligada e `RemoteAccessAllowed: false`** — o servidor só
  aceita conexões da própria máquina. É protótipo local com dado anonimizado.
- **CORS liberado** — o OHIF roda em outra porta (3000/8080) e precisa disso.
- **Worklist desligada** — ligue (`Worklists.Enable: true`) se quiser simular o
  fluxo "exame agendado → chega no PACS", útil didaticamente.

Se um dia isto tocar dado real, o mínimo antes disso: `AuthenticationEnabled:
true` com `RegisteredUsers`, HTTPS, storage criptografado e trilha de auditoria
— e passar por TI/compliance (ver docs/ARQUITETURA.md).
