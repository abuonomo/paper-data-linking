#!/usr/bin/env bash
#
# Pull-based deploy for paper-data-linking.
#
# CI (GitHub Actions) builds the api/client images and pushes them to a
# container registry. Production does NOT run a CI runner or accept any inbound
# connection — it simply pulls the latest code + images and converges. Run this
# on a timer (see deploy/pdl-deploy.timer.example) for automatic deployment, or
# by hand to deploy on demand. It is idempotent: if nothing changed it is a
# no-op.
#
# Requirements: git, docker, docker compose. Outbound network only.
#
# Configuration (environment, or the .env that docker compose reads in DEPLOY_DIR):
#   DEPLOY_DIR   path to the deploy checkout of this repo
#                (default: the parent of this script's directory)
#   PDL_IMAGE_REPO, NGINX_SERVER_NAME, NGINX_FLOWER_SERVER_NAME, app secrets:
#                set these in DEPLOY_DIR/.env
#
# NOTE: install this script OUTSIDE the deploy checkout (e.g. /usr/local/bin)
# so the `git reset` below cannot overwrite it mid-run. See deploy/README.md.

set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BRANCH="${DEPLOY_BRANCH:-main}"
cd "$DEPLOY_DIR"

compose() { docker compose -f docker-compose.yaml -f docker-compose.prod.yaml "$@"; }

# 1. Fast-forward the checkout to the latest published commit.
#    Tracked files are reset; untracked files (.env, nginx/.htpasswd,
#    client/.env.production.local) and docker volumes are left untouched.
git fetch --quiet origin "$BRANCH"
before="$(git rev-parse HEAD)"
git reset --quiet --hard "origin/${BRANCH}"
after="$(git rev-parse HEAD)"

# 2. Pull the latest images and converge. `up -d` only recreates containers
#    whose image digest actually changed, so an unchanged deploy is a no-op.
compose pull --quiet
compose up -d

# 3. Reclaim space from superseded images.
docker image prune -f >/dev/null 2>&1 || true

if [ "$before" != "$after" ]; then
  echo "deployed ${before:0:12} -> ${after:0:12}"
else
  echo "no code change; images reconciled"
fi
