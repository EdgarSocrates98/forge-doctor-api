#!/usr/bin/env bash
# Forge account install — editable runtime + user-scoped environment.
set -euo pipefail
cd "$(dirname "$0")"
PY="$(command -v python3 || command -v python || command -v py)"
if [ -z "$PY" ]; then
  echo "install: no python on PATH (need >=3.10)" >&2; exit 2
fi
ARGS=(--editable --persist-env --allow-download "$@")
if [ "${PY##*/}" = "py" ]; then "$PY" -3 scripts/forge_bootstrap.py "${ARGS[@]}"; else "$PY" scripts/forge_bootstrap.py "${ARGS[@]}"; fi
status=$?
if [ "$status" -eq 0 ]; then
  echo "Install complete. Open new shell or run: source ~/.config/forjas/env.sh"
fi
exit "$status"
