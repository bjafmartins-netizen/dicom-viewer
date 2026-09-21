# data/

Pasta de trabalho para arquivos DICOM. **O conteúdo não é versionado**
(ver `.gitignore`) — nenhum arquivo de imagem entra no repositório.

Organização sugerida:

```
data/
├── phantom/       <- dataset sintético (scripts/make_phantom_dataset.py)
├── bruto/         <- arquivos como chegaram, ainda não anonimizados
└── anonimizado/   <- saída de metadata.anonymize, o que vai para o miniPACS
```

Gere um dataset de teste sem baixar nada:

```bash
python scripts/make_phantom_dataset.py --output data/phantom
```
