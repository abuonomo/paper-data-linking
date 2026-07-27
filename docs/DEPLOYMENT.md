# Deployment

Production runs the same Docker Compose stack as local development, with a
production overlay (`docker-compose.prod.yaml`) that pulls prebuilt images from
a container registry and adds per-container memory limits and restart policies.

## Prerequisites

- Docker and Docker Compose on the host.
- A set of images built from this repo and pushed to a container registry you
  control (see **Building images** below).
- A production `.env` (copy from `.env_example` and fill in real values).
- A `client/.env.production.local` with your real frontend values (this file is
  gitignored; Vite loads it with higher priority than the committed
  `client/.env.production`):

  ```
  VITE_BASE_URL=your-domain.example.com
  VITE_BASE_PROTOCOL=https
  VITE_CONTACT_EMAIL=you@example.com
  ```

## Configuration

Set these in the host environment (or the production `.env`); the compose files
read them at deploy time:

| Variable | Purpose | Example |
|---|---|---|
| `PDL_IMAGE_REPO` | Registry image path (without the `/api` or `/client` suffix) | `registry.example.com/your-org/paper-data-linking` |
| `NGINX_SERVER_NAME` | Public hostname for the app vhost | `paper-data.example.com` |
| `NGINX_FLOWER_SERVER_NAME` | Hostname for the Flower dashboard vhost | `flower.paper-data.example.com` |

If `PDL_IMAGE_REPO` is unset, the overlay falls back to the local image name
`paper-data-linking/*:latest`. If the nginx server-name variables are unset, the
app vhost uses nginx's catch-all (`_`), which is fine for a single-domain host.

Secrets (Django secret key, database credentials, API tokens, AWS credentials,
the nginx basic-auth password) live **only** on the host — in the `.env`, in the
container secrets store, or in `nginx/.htpasswd`. Never commit them.

## Building images

```bash
docker build -t $PDL_IMAGE_REPO/api:latest .
docker build --build-arg BUILD_MODE=production -t $PDL_IMAGE_REPO/client:latest ./client
docker push $PDL_IMAGE_REPO/api:latest
docker push $PDL_IMAGE_REPO/client:latest
```

## Deploy

From the deploy directory on the host:

```bash
git pull origin main
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml pull
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d
```

You can wire the build + deploy steps above into whatever CI/CD system you use
(GitHub Actions, GitLab CI, a cron job, or a manual runbook).
