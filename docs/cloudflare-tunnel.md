# Cloudflare Tunnel Setup

Exposes the local stack to the internet via a stable HTTPS URL on `charlytoc.dev`, without opening firewall ports.

Traffic hits Cloudflare → tunnel → nginx on `ENTRYPOINT_PORT` → Django / Realtime / Next.js.

## Prerequisites

- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) installed
- `charlytoc.dev` managed in your Cloudflare account

## One-time setup

### 1. Authenticate

```bash
cloudflared tunnel login
```

Opens a browser to authorize cloudflared against your Cloudflare account. Creates `~/.cloudflared/cert.pem`.

### 2. Create the tunnel

```bash
cloudflared tunnel create coworkers
```

Creates the tunnel and writes credentials to `~/.cloudflared/<uuid>.json`.

### 3. Route a hostname

```bash
cloudflared tunnel route dns coworkers coworkers.charlytoc.dev
```

Adds a CNAME in Cloudflare DNS pointing `coworkers.charlytoc.dev` to the tunnel. Only needed once.

## Running the tunnel

Make sure the stack is up (`./taskfile.sh start`) and the web frontend is running (`./taskfile.sh web`), then:

```bash
./taskfile.sh tunnel
```

The app will be live at `https://coworkers.charlytoc.dev`.

## Notes

- The tunnel reads `ENTRYPOINT_PORT` from `.env` (default `9000`) — make sure nginx is running on that port.
- Credentials live in `~/.cloudflared/<uuid>.json`. Do not commit them.
- To stop the tunnel, `Ctrl+C` in the terminal running `./taskfile.sh tunnel`.
