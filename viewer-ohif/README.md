# viewer-ohif/ — OHIF Viewer

O OHIF é o visualizador web "de verdade" (séries, scroll, janelamento,
medidas, MPR). Ele é uma aplicação **estática**: compila-se uma vez, e depois
basta servir a pasta resultante por qualquer servidor HTTP. Node só é
necessário na hora de compilar, não para usar.

O build **não está versionado** aqui (são dezenas de MB). Versionado é só o
`ohif-config.js`, que aponta o viewer para o Orthanc local.

> **Sem Node/Yarn na máquina?** Não precisa compilar nada: use o **Stone Web
> Viewer**, plugin do próprio Orthanc, que entrega scroll de série,
> janelamento, medidas e MPR. Instruções em `pacs/README.md`. O OHIF abaixo
> continua valendo para quem quiser a interface dele ou suas extensões.

## Compilar (uma vez, numa máquina com Node 18+ e Yarn)

```bash
git clone https://github.com/OHIF/Viewers.git
cd Viewers
yarn install
yarn run build
```

O resultado fica em `Viewers/platform/app/dist/`. Copie essa pasta para cá:

```
viewer-ohif/
├── ohif-config.js      <- versionado (este repositório)
└── dist/               <- build do OHIF (não versionado)
    ├── index.html
    ├── app-config.js   <- SUBSTITUA pelo ohif-config.js
    └── ...
```

Passo final: sobrescreva `dist/app-config.js` com o `ohif-config.js` daqui.

```cmd
copy /Y viewer-ohif\ohif-config.js viewer-ohif\dist\app-config.js
```

```bash
cp viewer-ohif/ohif-config.js viewer-ohif/dist/app-config.js
```

## Servir

```bash
python -m http.server 3000 --directory viewer-ohif/dist
```

Abra http://localhost:3000. Ou use `scripts/start_all.sh` /
`scripts\start_all.bat`, que sobem Orthanc + OHIF de uma vez.

## Se a lista de estudos aparecer vazia

1. O Orthanc está rodando? `curl http://localhost:8042/system`
2. Tem exame importado? `curl http://localhost:8042/statistics`
3. O DICOMweb responde? `curl http://localhost:8042/dicom-web/studies`
   — se der 404, o plugin DICOMweb não carregou (confira `pacs/plugins/`).
4. Erro de CORS no console do navegador? Confira o bloco `HttpHeaders` em
   `pacs/orthanc.json` e reinicie o Orthanc.
5. Mudou a porta do Orthanc? Ela aparece em três lugares no `ohif-config.js`
   (`wadoUriRoot`, `qidoRoot`, `wadoRoot`).

## Alternativa mais leve

Para checagem rápida de um arquivo solto, sem subir nada:
`python viewer_legacy/sico.py`.
