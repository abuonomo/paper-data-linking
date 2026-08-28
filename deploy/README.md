# Deployment

Two independent halves:

- **Build (CI):** GitHub Actions (`.github/workflows/build.yml`) builds the `api`
  and `client` images and pushes them to the container registry on every push to
  `main`.
- **Deploy (CD):** the production host **pulls** the latest code and images and
  converges. No CI runner and no inbound connection to the host are required —
  the host only makes outbound calls to the git host and the registry. This is
  the safest option for a locked-down / firewalled host.

See also `../docs/DEPLOYMENT.md` for the underlying compose/registry model and
the environment variables the compose files expect.

## Prerequisites on the host

1. A checkout of this repo at your deploy directory (e.g. `/opt/paper-data-linking`).
2. A prod `.env` in that directory (copy from `.env_example`) with at least:
   ```
   PDL_IMAGE_REPO=<registry>/<owner>/paper-data-linking
   NGINX_SERVER_NAME=your-domain.example.com
   NGINX_FLOWER_SERVER_NAME=flower.your-domain.example.com
   ```
   plus the app secrets (Django key, DB creds, API tokens).
3. If the registry images are private, `docker login <registry>` once. If they
   are public, no login is needed.

## Manual deploy

```bash
DEPLOY_DIR=/opt/paper-data-linking deploy/deploy-pull.sh
```

## Automatic deploy (systemd timer)

Install the script **outside** the deploy checkout so a `git reset` can't
overwrite it mid-run, then enable the timer:

```bash
sudo install -m 0755 deploy/deploy-pull.sh /usr/local/bin/pdl-deploy

sudo cp deploy/pdl-deploy.service.example /etc/systemd/system/pdl-deploy.service
sudo cp deploy/pdl-deploy.timer.example   /etc/systemd/system/pdl-deploy.timer
# edit DEPLOY_DIR / User in pdl-deploy.service

sudo systemctl daemon-reload
sudo systemctl enable --now pdl-deploy.timer
```

Watch it:

```bash
systemctl list-timers pdl-deploy.timer
journalctl -u pdl-deploy.service -f
```

Push to `main` → CI builds the images → the timer pulls and redeploys within its
interval. To deploy immediately without waiting for the timer:
`sudo systemctl start pdl-deploy.service`.

## Read-only external access (bulk consumers)

External systems that need to read the database in bulk (rather than through
the HTTP API) get two things, both provisioned by
`deploy/provision-readonly-access.sh` run on the host from the deploy
directory:

- **`pdl_readonly`** — a SELECT-only postgres role with guardrails:
  `statement_timeout = 30min` and `CONNECTION LIMIT 2`, so a runaway external
  query can't starve the app. A `DEFAULT PRIVILEGES` grant keeps tables from
  future migrations readable. The generated password lands in
  `~/pdl_readonly.credentials` (mode 600); share it over a secure channel and
  delete the file.
- **`pdltunnel`** — an SSH user with no password and no shell, used only to
  tunnel to postgres. The consumer's public key must be added to
  `/home/pdltunnel/.ssh/authorized_keys` with a restriction prefix that
  disables everything except forwarding to the database port:

  ```
  restrict,port-forwarding,permitopen="localhost:5432" ssh-ed25519 AAAA... comment
  ```

The consumer runs a persistent tunnel (autossh or a systemd unit):

```bash
ssh -N -L 5433:localhost:5432 pdltunnel@<host>
```

and points its postgres client at `localhost:5433`. No security-group changes
and no TLS setup are needed — nothing new is exposed and the tunnel encrypts
the traffic.

Guidance for consumers doing bulk pulls:

- Prefer `COPY (SELECT ...) TO STDOUT` or keyset pagination
  (`WHERE id > :last ORDER BY id LIMIT n`) over `OFFSET`; keep transactions
  short so vacuum isn't held back.
- Recurring ingests should use an `updated_at` watermark instead of re-pulling
  everything, and run off-peak where possible.
- Ask consumers for the list of tables/columns they read, so schema migrations
  can be checked against downstream breakage before they ship.

The role is read-only by grants, not a replica: it still consumes connections
and can hold locks, which is what the guardrails bound.
