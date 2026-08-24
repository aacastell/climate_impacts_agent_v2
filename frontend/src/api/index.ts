import type { ApiClient } from "./types";
import { HttpApiClient } from "./httpClient";
import { MockApiClient } from "./mockClient";
import { PrecomputedApiClient } from "./precomputedClient";

// No API tier exists yet (see repo README "Status" table), so default to
// the fully-synthetic mock client. Two ways to opt out of it, checked in
// order: VITE_USE_PRECOMPUTED_API=true selects real process-stage output
// (see pipeline/climate_pipeline/process/, served at /precomputed/regions.json)
// with no backend still required; VITE_USE_MOCK_API=false selects the real
// HTTP client, for once an API tier exists.
const usePrecomputed = import.meta.env.VITE_USE_PRECOMPUTED_API === "true";
const useMock = import.meta.env.VITE_USE_MOCK_API !== "false";

export const apiClient: ApiClient = usePrecomputed
  ? new PrecomputedApiClient()
  : useMock
    ? new MockApiClient()
    : new HttpApiClient();

export type {
  ApiClient,
  ClimateMapPayload,
  Crop,
  MapCenter,
  Provenance,
  QueryAnswer,
  QueryInterpretation,
  QueryRefusal,
  QueryRequest,
  QueryResponse,
  RefusalReason,
  SectorMapPayload,
} from "./types";
