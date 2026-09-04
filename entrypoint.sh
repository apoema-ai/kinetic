#!/bin/bash
set -euo pipefail

echo "[byond] Installing/updating Claude Code..."
npm install -g @anthropic-ai/claude-code@latest

echo "[byond] Byond is up. Get a shell with:"
echo "[byond]   docker compose exec -it byond bash"
echo "[byond] First time in, log in to Claude Code with: claude login"

exec sleep infinity
