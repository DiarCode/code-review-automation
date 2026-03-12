#!/usr/bin/env bash
set -euo pipefail

GITHUB_TOKEN="YOUR GITHUB TOKEN"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Quick sanity check
echo "🔑  Token starts with: ${GITHUB_TOKEN:0:10}..."
echo "🔗  URL: $1"

if [[ $# -eq 0 ]]; then
  echo "❌  Usage: ./run.sh <PR_URL>"
  exit 1
fi

export GITHUB_TOKEN
cd "$SCRIPT_DIR"
uv run main.py "$1"