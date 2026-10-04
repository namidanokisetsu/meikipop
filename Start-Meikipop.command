#!/bin/zsh
set -eu
cd -- "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  print -u2 'Create the environment first: python3 -m venv .venv && .venv/bin/python -m pip install -e .'
  read -r '?Press Return to close.'
  exit 1
fi
exec .venv/bin/python -m meikipop.scripts.quick_lookup "$@"
