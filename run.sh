#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Check if .env exists in parent or current
if [ ! -f .env ] && [ -f ../.env ]; then
    cp ../.env .env
    echo "Copied .env from parent directory"
fi

if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Create one from .env.example"
    exit 1
fi

echo "Starting Flask dashboard..."
python3 app.py
