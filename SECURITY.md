# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 1.1.x | yes |
| 1.0.x | reproducibility reference for the companion paper only; no security fixes |

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's private vulnerability reporting ("Report a vulnerability" under the Security tab) or email anthony.r.buonomo@nasa.gov. You will get an acknowledgement within 7 days and a fix or mitigation plan as soon as the impact is understood.

## Scope notes

- The public API under `/builder/public/` is read-only and unauthenticated by design; everything else requires a JWT.
- Paper full texts are publisher-licensed. Endpoints that return them require authentication.
- Deployments should keep the admin and validation interfaces behind HTTPS; see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
