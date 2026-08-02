# MOMO Scholar Web

Stage 4 local-only React frontend. It follows
`docs/superpowers/specs/2026-08-02-web-mvp-scope-api-ui-contract.md` and does not
import Python modules or inspect pipeline outputs.

## Run the integrated local UI

```sh
npm ci
npm run contracts:check
npm run build
cd ..
python -m paper_agent.web
```

Open `http://127.0.0.1:8000`. FastAPI serves the production build and `/api/v1`
from the same origin. The packaged synthetic demo is available without provider
configuration or network access. Creating a live run still uses the normal
production pipeline and therefore needs its normal provider configuration.

## Vite development proxy

Start the API with the exact Vite browser origin and then start Vite:

```sh
python -m paper_agent.web --dev-origin http://127.0.0.1:5173
cd web
npm run dev
```

Browser requests remain same-origin to Vite and `/api` is proxied exactly to
`http://127.0.0.1:8000`. CORS is disabled unless an exact `--dev-origin` is
provided; wildcard origins are rejected.

For the deterministic browser fixture only, set `VITE_API_MODE=mock`. Production
and normal development default to the real same-origin HTTP API.

## Connect the real local API

The switch between fixture and live data remains behind the `RunApi` boundary.
`openapi/web-v1.json` is generated from FastAPI and
`src/api/openapi.generated.ts` is generated from that snapshot.

## Verify

```sh
npm test
npm run build
npm run contracts:check
```

The test suite is deterministic and offline.
