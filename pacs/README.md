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
