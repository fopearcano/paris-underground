#!/usr/bin/env bash
# One-command launcher for macOS: double-click in Finder, or run ./start.command
# Creates a local virtual environment on first run, installs dependencies,
# then serves the atlas at http://127.0.0.1:8000 and opens it in the browser.
set -euo pipefail
cd "$(dirname "$0")"

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if [ ! -x .venv/bin/python ]; then
  if ! PYTHON="$(find_python)"; then
    echo "Paris Underground needs Python 3.11 or newer."
    echo "Install it from https://www.python.org/downloads/macos/ or with Homebrew: brew install python@3.12"
    read -r -p "Press Return to close." _ || true
    exit 1
  fi
  echo "Creating a virtual environment with $PYTHON…"
  "$PYTHON" -m venv .venv
fi

# Reinstall dependencies only when requirements.txt changes.
STAMP=.venv/.requirements.sha
CURRENT="$(shasum requirements.txt | cut -d' ' -f1)"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$CURRENT" ]; then
  echo "Installing dependencies…"
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  echo "$CURRENT" > "$STAMP"
fi

exec .venv/bin/python run.py "$@"
