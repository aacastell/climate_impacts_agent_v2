# Frontend

React + TypeScript + Vite + MapLibre GL JS, per [ADR-002](../docs/adr/adr-002-frontend-framework.md).

## Setup

Node version is pinned in `.nvmrc`.

```sh
nvm use
npm install
npm run dev
```

## Scripts

- `npm run dev` — dev server
- `npm run build` — typecheck (`tsc -b`) then production build
- `npm run lint` — oxlint
- `npm run preview` — serve the production build locally

## API tier

Not yet decided (see repo root README "Status" table). `src/api/` defines the
contract the frontend needs (`src/api/types.ts`) against an `ApiClient`
interface with two implementations:

- `MockApiClient` — deterministic fake data, used by default in dev
  (`VITE_USE_MOCK_API=true` in `.env.development`).
- `HttpApiClient` — calls `POST /api/query` on the same origin, per
  [ADR-001](../docs/adr/adr-001-frontend-hosting.md)'s single-distribution
  routing. Not wired to anything real yet.

Switch by setting `VITE_USE_MOCK_API=false` once a real endpoint exists.

## Notes

- Dependency tree is deliberately small (ADR-002): `react`, `react-dom`,
  `maplibre-gl` are the only runtime dependencies.
- Maps use MapLibre's hosted demo style as a placeholder basemap — real tile
  serving is still open.
- `ClimateMapPayload.value` is always a single number and `SectorMapPayload.range`
  is always a `[min, max]` tuple, enforced in the type system — see the
  comments in `src/api/types.ts` for why (single climate model vs. two crop
  models; the repo root README's "two facts that must appear in every
  answer").
