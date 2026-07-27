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
