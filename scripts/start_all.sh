#!/usr/bin/env bash
# Sobe o miniPACS completo: Orthanc + OHIF servido por HTTP estático.
# Ctrl+C derruba os dois.
#
#   ./scripts/start_all.sh            # portas padrão (8042 e 3000)
#   OHIF_PORT=8080 ./scripts/start_all.sh
set -uo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACS_DIR="$RAIZ/pacs"
OHIF_DIST="$RAIZ/viewer-ohif/dist"
OHIF_PORT="${OHIF_PORT:-3000}"
ORTHANC_PORT="${ORTHANC_PORT:-8042}"

PIDS=()
encerrar() {
  echo ""
  echo "Encerrando..."
  for pid in "${PIDS[@]:-}"; do
    [ -n "${pid:-}" ] && kill "$pid" 2>/dev/null
  done
  wait 2>/dev/null
  exit 0
}
trap encerrar INT TERM

# --- Orthanc ---------------------------------------------------------------
ORTHANC_BIN=""
if [ -x "$PACS_DIR/Orthanc" ]; then
  ORTHANC_BIN="$PACS_DIR/Orthanc"
elif command -v Orthanc >/dev/null 2>&1; then
  ORTHANC_BIN="$(command -v Orthanc)"
elif command -v orthanc >/dev/null 2>&1; then
  ORTHANC_BIN="$(command -v orthanc)"
fi

if [ -z "$ORTHANC_BIN" ]; then
  echo "ERRO: Orthanc não encontrado."
  echo "Coloque o binário em pacs/ ou instale-o (veja pacs/README.md)."
  exit 1
fi

echo "Orthanc: $ORTHANC_BIN"
( cd "$PACS_DIR" && "$ORTHANC_BIN" orthanc.json ) &
PIDS+=($!)

# Espera o servidor responder antes de seguir
for _ in $(seq 1 30); do
  if curl -fsS "http://localhost:$ORTHANC_PORT/system" >/dev/null 2>&1; then
    echo "Orthanc no ar: http://localhost:$ORTHANC_PORT"
    break
  fi
  sleep 0.5
done

# --- OHIF ------------------------------------------------------------------
if [ -d "$OHIF_DIST" ]; then
  python3 -m http.server "$OHIF_PORT" --directory "$OHIF_DIST" >/dev/null 2>&1 &
  PIDS+=($!)
  echo "OHIF no ar:    http://localhost:$OHIF_PORT"
elif ls "$PACS_DIR"/plugins/*StoneWebViewer* >/dev/null 2>&1; then
  echo "Build do OHIF não encontrado; use o Stone Web Viewer (plugin do Orthanc):"
  echo "               http://localhost:$ORTHANC_PORT/stone-webviewer/index.html"
else
  echo "AVISO: nenhum viewer instalado (nem OHIF em viewer-ohif/dist, nem plugin Stone)."
  echo "       Veja pacs/README.md. A interface própria do Orthanc já mostra as imagens."
fi

echo ""
echo "Orthanc Explorer: http://localhost:$ORTHANC_PORT"
echo "Importar exames:  python scripts/import_folder.py --input data/phantom"
echo "Ctrl+C encerra."
wait
