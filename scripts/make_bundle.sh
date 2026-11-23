#!/usr/bin/env bash
# Génère dist/babelgrade-bundle.tar.gz (bundle Docker autonome).
# Usage : scripts/make_bundle.sh [version]      (défaut : 0.1.0)
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${1:-0.1.0}"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
DEST="$STAGE/babelgrade-bundle"
mkdir -p "$DEST" dist

cp -R Dockerfile docker-compose.yml .env.example .dockerignore \
      requirements.txt run.sh app static docs LICENSE README.md "$DEST/"
rm -rf "$DEST"/docs/{assets,readme,onepager-fr}
find "$DEST" -name __pycache__ -prune -exec rm -rf {} +
sed -i.bak "s/babelgrade:[0-9.]*/babelgrade:${VERSION}/" "$DEST/docker-compose.yml" && rm "$DEST/docker-compose.yml.bak"

cat > "$DEST/QUICKSTART.txt" <<TXT
BabelGrade v${VERSION} — bundle Docker

  cp .env.example .env        # optionnel
  docker compose up -d --build
  -> http://localhost:8090    (santé : /api/health)

Un seul conteneur : front FastAPI + workers (file de jobs asyncio).
Prérequis : Docker + serveur LLM compatible OpenAI (défaut : http://host.docker.internal:8078/v1).
TXT

COPYFILE_DISABLE=1 tar -czf dist/babelgrade-bundle.tar.gz -C "$STAGE" babelgrade-bundle
echo "OK -> dist/babelgrade-bundle.tar.gz ($(du -h dist/babelgrade-bundle.tar.gz | cut -f1))"
