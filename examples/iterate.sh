#!/usr/bin/env bash
# Two versions of the same brief, then a side-by-side content-score diff.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-.mcw}"
python3 -m mcw run briefs/creditcard-official.yaml --mock --run-id demo-card --out "$OUT"
python3 -m mcw run briefs/creditcard-official.yaml --mock \
  --continue-run demo-card \
  --out "$OUT" \
  --reviewer 林可 \
  --comment "删掉口头禅，保留审批声明" \
  --approval examples/approval-approved.json
python3 -m mcw compare demo-card --left v1 --right v2 --out "$OUT"
python3 -m mcw list-versions demo-card --out "$OUT"
