#!/usr/bin/env bash
# Provision read-only external access to the prod database:
#   1. a SELECT-only postgres role (pdl_readonly) with load guardrails, and
#   2. a tunnel-only SSH user (pdltunnel) that can reach port 5432 and nothing else.
#
# Run ON the production host, from the deploy directory (where the compose
# files and prod .env live). Safe to re-run: existing role/user are kept and
# grants are re-applied. Requires sudo for the SSH-user half.
#
# The generated DB password is written to ~/pdl_readonly.credentials (mode 600)
# — share it with the consumer over a secure channel, then delete the file.
set -euo pipefail

COMPOSE=(docker compose -f docker-compose.yaml -f docker-compose.prod.yaml)
# Pull creds out of .env with grep — the file is not `source`-able (unquoted
# special characters in some values abort the shell).
DB_USER=$(grep -E '^DB_USER=' .env | cut -d= -f2-)
DB_NAME=$(grep -E '^DB_NAME=' .env | cut -d= -f2-)

psql_exec() {
  "${COMPOSE[@]}" exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 "$@"
}

# --- 1. Database role -------------------------------------------------------
ROLE_EXISTS=$(psql_exec -tAc "SELECT 1 FROM pg_roles WHERE rolname='pdl_readonly'")
if [[ "$ROLE_EXISTS" != "1" ]]; then
  PW=$(openssl rand -base64 24)
  umask 077
  printf 'database: %s\nuser: pdl_readonly\npassword: %s\nconnect via SSH tunnel to this host, port 5432\n' \
    "$DB_NAME" "$PW" > ~/pdl_readonly.credentials
  psql_exec -c "CREATE ROLE pdl_readonly LOGIN PASSWORD '$PW'"
  echo "created role pdl_readonly; credentials written to ~/pdl_readonly.credentials"
else
  echo "role pdl_readonly already exists; leaving password unchanged"
fi

psql_exec <<SQL
GRANT CONNECT ON DATABASE $DB_NAME TO pdl_readonly;
GRANT USAGE ON SCHEMA public TO pdl_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO pdl_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE $DB_USER IN SCHEMA public GRANT SELECT ON TABLES TO pdl_readonly;
ALTER ROLE pdl_readonly SET statement_timeout = '30min';
ALTER ROLE pdl_readonly CONNECTION LIMIT 2;
SQL
echo "grants + guardrails applied (SELECT-only, 30min statement_timeout, 2 connections)"

# --- 2. Tunnel-only SSH user ------------------------------------------------
if ! id pdltunnel &>/dev/null; then
  sudo adduser --disabled-password --gecos "" --shell /usr/sbin/nologin pdltunnel
  echo "created system user pdltunnel (no password, no shell)"
else
  echo "system user pdltunnel already exists"
fi
sudo mkdir -p /home/pdltunnel/.ssh
sudo touch /home/pdltunnel/.ssh/authorized_keys
sudo chown -R pdltunnel:pdltunnel /home/pdltunnel/.ssh
sudo chmod 700 /home/pdltunnel/.ssh
sudo chmod 600 /home/pdltunnel/.ssh/authorized_keys

cat <<'EOF'

Done. Remaining manual step — when you have the consumer's SSH public key,
append it to /home/pdltunnel/.ssh/authorized_keys with this restriction prefix
(one line, key material in place of AAAA...):

  restrict,port-forwarding,permitopen="localhost:5432" ssh-ed25519 AAAA... comment

The consumer then tunnels with:

  ssh -N -L 5433:localhost:5432 pdltunnel@<this host>

and connects postgres clients to localhost:5433 using ~/pdl_readonly.credentials.
EOF
