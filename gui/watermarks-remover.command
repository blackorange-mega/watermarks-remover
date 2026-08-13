#!/usr/bin/env bash
# Double-click launcher for macOS, and a normal script on Linux.
set -euo pipefail
cd "$(dirname "$0")"

for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    exec "$candidate" launch.py "$@"
  fi
done

echo
echo "  Python 3.10 or newer is required to run watermarks-remover."
echo "  macOS:  brew install python"
echo "  Linux:  sudo apt install python3 python3-tk"
echo
read -r -p "Press Enter to close." _
exit 1
