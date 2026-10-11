#!/usr/bin/env bash
# Local Linux build: PyInstaller onedir + tar.gz + nfpm deb.
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_VERSION="${APP_VERSION:-0.0.0-dev}"

PY="${PYTHON:-python3}"
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi

printf '%s' "$APP_VERSION" > _version.txt

"$PY" -m PyInstaller packaging/nexadesk.spec --noconfirm --distpath dist --workpath build

# Regression guard: the lazy OCR import must still be in the bundle.
for pkg in rapidocr_onnxruntime onnxruntime; do
  if [ ! -d "dist/NexaDesk/_internal/$pkg" ]; then
    echo "error: $pkg missing from dist/NexaDesk/_internal" >&2
    exit 1
  fi
done

tar -czf "dist/NexaDesk_${APP_VERSION}_linux_amd64.tar.gz" -C dist NexaDesk
NFPM="$(command -v nfpm || echo "$HOME/.local/bin/nfpm")"
"$NFPM" package --config packaging/nfpm.yaml --packager deb --target "dist/NexaDesk_${APP_VERSION}_amd64.deb"
echo "built: dist/NexaDesk/ + tar.gz + deb"
