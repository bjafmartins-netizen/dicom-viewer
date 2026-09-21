# Arquitetura — dicom-viewer → miniPACS

Contexto: uso de teste/estudo, com dados anonimizados (phantoms, datasets públicos como TCIA). Sem dados reais de paciente por ora — os pontos de extensão para autenticação/auditoria estão marcados abaixo caso isso mude no futuro.

Restrição de ambiente: sem Docker disponível por padrão (pode depender de TI). Todo o stack abaixo foi escolhido para rodar **sem instalação nem admin no Windows**, inclusive de um pendrive.

## Visão geral dos componentes

```
[Pasta de exames DICOM] --> [Orthanc portátil]  (servidor DICOM + DICOMweb + storage)
                                    |
                                    | DICOMweb (QIDO-RS / WADO-RS / STOW-RS)
                                    v
                          [OHIF Viewer]  (app web estática, aponta pro Orthanc)

[sico.py / módulo de metadados] --> lê arquivos DICOM direto OU consulta a API REST do Orthanc
                                 --> exporta CSV/JSON/DataFrame
```

Orthanc funciona como o "miniPACS" propriamente dito: recebe, guarda e indexa os exames, e já fala o protocolo DICOMweb nativamente (plugin embutido desde versões recentes) — então o OHIF conecta nele sem nenhum adaptador extra. Isso elimina a necessidade de escrever um servidor DICOMweb do zero.

## Componentes em detalhe

### 1. `pacs/` — Orthanc portátil
- Binário `.exe` portátil do Orthanc para Windows (não precisa instalar, não precisa admin).
- `orthanc.json`: config mínima — pasta de storage local, porta HTTP (ex. 8042), plugin DICOMweb habilitado.
- Interface web própria do Orthanc (Orthanc Explorer) já dá visualização básica, busca por paciente/estudo/série, e upload manual de arquivos — útil mesmo antes do OHIF estar pronto.
- Ponto de extensão futuro: autenticação (Orthanc suporta usuário/senha nativo), HTTPS, plugin de auditoria de acesso.

### 2. `metadata/` — extração de metadados
Evolução do `sico.py` atual, separada em módulo reutilizável (hoje o `sico.py` mistura leitura de metadados com a interface gráfica):
- `extract_metadata.py`: função que recebe um dataset pydicom e devolve um dicionário/DataFrame com as tags relevantes (paciente anonimizado, modalidade, estudo, série, equipamento, parâmetros de aquisição — TR/TE, kVp, mAs, slice thickness, etc., dependendo da modalidade).
- CLI: `python extract_metadata.py --input pasta/ --output metadata.csv` — varre uma pasta inteira e consolida tudo num CSV/JSON, útil para pesquisa.
- Também pode consultar direto a API REST do Orthanc (`/instances/{id}/tags`) para não precisar reabrir os arquivos brutos.

### 3. `viewer-ohif/` — OHIF Viewer
- OHIF é compilado (`yarn build`) gerando uma pasta estática de HTML/JS/CSS.
- `ohif-config.js`: aponta o `dataSource` do OHIF para o endpoint DICOMweb do Orthanc local (`http://localhost:8042/dicom-web`).
- Servido por qualquer servidor HTTP simples (ex. `python -m http.server`), sem precisar de Node rodando em produção — só na hora de compilar.

### 4. `viewer_legacy/` — sico.py
- Mantido como estava (visualizador standalone simples), útil para checagem rápida de um único arquivo sem precisar subir o Orthanc.

### 5. `scripts/`
- `start_all.bat` (Windows) / `start_all.sh`: sobe o Orthanc portátil e serve o build do OHIF, tudo com um comando.
- `import_folder.py`: varre uma pasta e envia (STOW-RS) os arquivos pro Orthanc automaticamente — útil para importar um dataset de teste inteiro de uma vez.

## Funcionalidades sugeridas além do pedido original

- **Anonimização automática** (`metadata/anonymize.py`): já que a política é usar só dados anonimizados, um script pydicom que remove/hash campos identificáveis (nome, ID, data de nascimento, datas de exame) antes de importar qualquer arquivo novo pro miniPACS — evita erro humano de subir algo identificável por engano.
- **Exportação de metadados em lote para CSV/JSON/Parquet**, pensando em uso futuro para pesquisa (radiomics, estudos estatísticos) — já é praticamente grátis dado o módulo de extração.
- **Miniaturas (thumbnails)** por série, geradas com pydicom + matplotlib, para navegação mais rápida sem abrir o viewer completo.
- **Worklist simulado** (Orthanc tem suporte a Modality Worklist): útil para simular um fluxo de "exame agendado → chega no PACS → some da lista", bom para fins didáticos/estudo de fluxo de trabalho.
- **Datasets de teste prontos**: script para baixar um conjunto pequeno de exames públicos e anonimizados (ex. TCIA, ou os exemplos oficiais do Orthanc) para já ter algo pra testar sem precisar de arquivo próprio.

## Pontos de extensão (só se um dia isso tocar dados reais)
- Autenticação de usuário no Orthanc (nativo) + HTTPS.
- Trilha de auditoria de acesso (log de quem visualizou o quê).
- Criptografia em repouso do storage.
- Validação de conformidade LGPD/RDC antes de qualquer dado real entrar — isso precisaria passar pelo TI/compliance da SARAH, fora do escopo deste protótipo.

## Ordem de implementação sugerida

1. Orthanc portátil rodando local, importando manualmente 1-2 arquivos de teste pela própria interface web do Orthanc (valida que o servidor funciona antes de mexer em mais nada).
2. Refatorar `sico.py` → módulo `metadata/extract_metadata.py` com CLI.
3. Compilar OHIF apontando pro Orthanc local, confirmar que abre e renderiza uma série.
4. Scripts de automação (`start_all`, `import_folder`).
5. Recursos extras (anonimização, thumbnails, worklist) — nessa ordem de prioridade.

Este documento foi escrito para ser o ponto de partida ao abrir este repositório no Claude Code local.
