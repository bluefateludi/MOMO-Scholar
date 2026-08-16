# MOMO TechScout Web

Local-only React frontend for MOMO TechScout. It does not import Python modules
or inspect pipeline outputs directly; all product data crosses the versioned API.

## Run the integrated local UI

```sh
npm ci --ignore-scripts
npm run contracts:check
npm run build
cd ..
techscout serve
```

Open `http://127.0.0.1:8000`. FastAPI serves the production build and the v1/v2
APIs from the same origin. Fast Demo uses frozen synthetic evidence and needs no
provider or Docker. Verified is limited to the bounded Hero Case and depends on
provider/cache, Docker, and the externally enforced installation network.

## Vite development proxy

Start the API with the exact Vite browser origin and then start Vite:

```sh
techscout serve --dev-origin http://127.0.0.1:5173
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
