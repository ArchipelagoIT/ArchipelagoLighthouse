#!/usr/bin/env bash
# Runs the guard with the SYSTEM Python in isolated mode (-I -S): no user site-packages,
# no .pth start-up files, no PYTHON* variables, so nothing the agent can write runs inside it.
# Fails CLOSED (exit 2) if no Python is found. settings.json adds "|| exit 2" in case this
# file itself is missing.
for py in /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if [ -x "$py" ]; then
    exec "$py" -I -S "$(dirname "$0")/guard.py"
  fi
done
echo "BLOCKED: guard needs python3 (macOS: xcode-select --install)." >&2
exit 2
