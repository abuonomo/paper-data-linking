#!/usr/bin/env bash
# Nightly logical backup of the production database to S3.
#
# Streams `pg_dump -Fc` from the postgres container straight to S3; nothing
# is written to the host's disk. The object goes under one of three prefixes
# so bucket lifecycle rules can keep different numbers of each:
#   monthly/  on the 1st of the month
#   weekly/   on Sundays
#   daily/    otherwise
# On success it writes status/last-success.json; on failure it uploads a
# <key>.FAILED marker, because a dump that dies mid-stream can still leave a
# truncated object behind.
#
# Credentials: the host's own AWS identity, or, if BACKUP_ROLE_ARN is set, a
# role assumed for the run (recommended: a role that can only PutObject, so
# nothing on the host can read or delete old backups).
#
# Restore:
#   aws s3 cp s3://$BACKUP_BUCKET/<key> backup.dump
#   pg_restore --no-owner --no-privileges -d <empty database> backup.dump
set -euo pipefail

: "${DEPLOY_DIR:?set DEPLOY_DIR to the deploy checkout (contains the prod .env)}"
: "${BACKUP_BUCKET:?set BACKUP_BUCKET}"
BACKUP_REGION="${BACKUP_REGION:-us-east-1}"
BACKUP_ROLE_ARN="${BACKUP_ROLE_ARN:-}"
PG_CONTAINER="${PG_CONTAINER:-}"

log() { echo "[pdl-db-backup] $*"; }

env_value() { grep -E "^$1=" "$DEPLOY_DIR/.env" | tail -1 | cut -d= -f2- | tr -d '"'"'"; }
DB_NAME="$(env_value DB_NAME)"
DB_USER="$(env_value DB_USER)"
: "${DB_NAME:?DB_NAME missing from .env}" "${DB_USER:?DB_USER missing from .env}"

if [ -z "$PG_CONTAINER" ]; then
  PG_CONTAINER="$(cd "$DEPLOY_DIR" && docker compose ps -q postgres | head -1)"
fi
[ -n "$PG_CONTAINER" ] || { log "postgres container not found"; exit 1; }

if [ -n "$BACKUP_ROLE_ARN" ]; then
  read -r AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN < <(
    aws sts assume-role --role-arn "$BACKUP_ROLE_ARN" --role-session-name "pdl-db-backup-$(hostname -s)" \
      --duration-seconds 7200 \
      --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text)
  export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [ "$(date -u +%d)" = "01" ]; then tier=monthly
elif [ "$(date -u +%u)" = "7" ]; then tier=weekly
else tier=daily; fi
key="$tier/${DB_NAME}-${stamp}.dump"
dest="s3://$BACKUP_BUCKET/$key"

log "dumping $DB_NAME from $PG_CONTAINER to $dest"
start=$(date +%s)
if ! docker exec "$PG_CONTAINER" nice -n 10 pg_dump -Fc -U "$DB_USER" -d "$DB_NAME" \
     | aws s3 cp - "$dest" --region "$BACKUP_REGION" --expected-size 50000000000 --only-show-errors; then
  log "FAILED after $(( $(date +%s) - start ))s"
  printf '{"key":"%s","failed_at":"%s"}\n' "$key" "$stamp" \
    | aws s3 cp - "$dest.FAILED" --region "$BACKUP_REGION" --only-show-errors || true
  exit 1
fi
secs=$(( $(date +%s) - start ))
size=$(aws s3api list-objects-v2 --bucket "$BACKUP_BUCKET" --prefix "$key" --region "$BACKUP_REGION" \
         --query 'Contents[0].Size' --output text)
printf '{"key":"%s","bytes":%s,"seconds":%s,"finished_at":"%s","host":"%s"}\n' \
  "$key" "${size:-null}" "$secs" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(hostname -s)" \
  | aws s3 cp - "s3://$BACKUP_BUCKET/status/last-success.json" --region "$BACKUP_REGION" --only-show-errors
log "ok: $key, ${size:-?} bytes in ${secs}s"
