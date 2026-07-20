#!/usr/bin/env bash
# Vendor rca_engine into the rca-recon skill and sync it to the Databricks
# workspace. The engine ships *inside* the skill folder so Genie Code imports it
# directly (no `pip install` from an external URL, which the workspace blocks).
#
# Usage: ./sync_skill.sh [databricks_profile]   (default profile: ps-dr-east)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SKILL="$ROOT/skill/rca-recon"
PROFILE="${1:-ps-dr-east}"

echo "==> Vendoring rca_engine into the skill"
rm -rf "$SKILL/rca_engine"
rsync -a --exclude '__pycache__' --exclude '*.pyc' "$ROOT/rca_engine/" "$SKILL/rca_engine/"

ME="$(databricks current-user me --profile "$PROFILE" -o json | python3 -c 'import sys,json;print(json.load(sys.stdin)["userName"])')"
DEST="/Users/$ME/.assistant/skills/rca-recon"

echo "==> Importing skill to $DEST"
databricks workspace import-dir "$SKILL" "$DEST" --overwrite --profile "$PROFILE"
echo "==> Done. Skill synced with vendored engine (no external install needed)."
