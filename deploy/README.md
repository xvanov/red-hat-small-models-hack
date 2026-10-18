# Public demo page (deploy/public_site)

One public page at **https://demo.rentus.homes**: how to try the leasing assistant (Messenger, SMS, email; any message gets an AI reply, no keyword), how it works, and live results. It is a separate FastAPI app; the private console (127.0.0.1:8080: inbox, send buttons, approvals) is never exposed.

## What the app serves

| Path | What |
|---|---|
| `GET /` | the page (`static/index.html`, values filled at request time) |
| `GET /static/{app.js,app.css,favicon.svg}` | assets (explicit allow-list) |
| `GET /api/results`, `/api/trust`, `/api/performance` | read-only proxy of the same console GETs, cached 60 s, rate-limited 30/min per client |
| `GET /api/online` | `{"online": bool}` from console `/api/status` (operator model reachable), cached 15 s |
| `GET /healthz` | liveness |

Everything else is 404, including every non-GET method, `/api/live/*`, `/api/runs*`, `/api/status`, `/approve`, `/docs`. Strict CSP (`script-src 'self'`, `form-action 'none'`, `frame-ancestors 'none'`); the page has no forms and all data is rendered with `textContent`. If the console is down the Results section stays hidden.

Displayed values: the Messenger link, the toll-free SMS number (only `TWILIO_PHONE_NUMBER` is read from `~/rental-management/.env.production`, validated as a phone number, or set `PUBLIC_SMS_NUMBER`), and the email address from `PUBLIC_DEMO_EMAIL` (the Email card is hidden until it is set). No other env value is read.

## Run

```bash
# app (port 8090 is taken by the labeler, so 8091)
nohup .venv/bin/python -m uvicorn deploy.public_site.app:app --host 127.0.0.1 --port 8091 > runs/public_site.log 2>&1 &

# named Cloudflare tunnel "rentus-demo" (separate from the rental-mgmt tunnel; its own config)
nohup cloudflared tunnel --no-autoupdate --config ~/.cloudflared/rentus-demo.yml run rentus-demo > runs/public_site_tunnel.log 2>&1 &
```

`~/.cloudflared/rentus-demo.yml` (not in the repo; credentials stay in `~/.cloudflared`):

```yaml
tunnel: dedef6ad-45ad-4cc1-849b-4b22e1eaae0c
credentials-file: /home/k/.cloudflared/dedef6ad-45ad-4cc1-849b-4b22e1eaae0c.json
ingress:
  - hostname: demo.rentus.homes
    service: http://127.0.0.1:8091
  - service: http_status:404
```

DNS was added once with `cloudflared tunnel --config ~/.cloudflared/rentus-demo.yml route dns --overwrite-dns dedef6ad-45ad-4cc1-849b-4b22e1eaae0c demo.rentus.homes`. Pass `--config` explicitly: without it cloudflared reads `~/.cloudflared/config.yml` and routes to the rental-mgmt tunnel instead. No other rentus.homes record was touched.

Fallback without the named tunnel: `cloudflared tunnel --url http://127.0.0.1:8091` (random trycloudflare.com URL).

## Test

```bash
.venv/bin/python -m pytest deploy/public_site/tests -q   # 404s, no writes, upstream allow-list, CSP, rate limit
```
