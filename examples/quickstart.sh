#!/usr/bin/env bash
# Offline quickstart. No API key.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install -e ".[dev]"
python3 -m mcw run briefs/sunscreen-xhs.yaml --mock --run-id demo-sunscreen --out .mcw
python3 -m mcw score --fixtures
python3 -m mcw list-versions demo-sunscreen --out .mcw
