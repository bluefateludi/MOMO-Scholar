# MOMO Scholar Web

Stage 4 local-only React frontend. It follows
`docs/superpowers/specs/2026-08-02-web-mvp-scope-api-ui-contract.md` and does not
import Python modules or inspect pipeline outputs.

## Run the contract fixture UI

```sh
npm install
npm run dev
```

Fixture mode is the default while the backend OpenAPI implementation is not on
`master`. It is visibly labelled throughout the UI and makes no provider calls.

## Connect the real local API

Copy `.env.example` to `.env.local`, set `VITE_API_MODE=live`, and start the Vite
development server. Requests under `/api` proxy to `http://127.0.0.1:8000`.
Production builds use same-origin `/api/v1` URLs.

The switch between fixture and live data is the `RunApi` boundary in
`src/api/contracts.ts`; route components do not know which implementation is in
use. When `openapi/web-v1.json` lands, the handwritten contract projection should
be replaced by its generated/mechanically checked output.

## Verify

```sh
npm test
npm run build
```

The test suite is deterministic and offline.
