#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")"
source .venv/bin/activate

python3 -m sophyane --doctor
python3 -m unittest discover -s tests -v
