import type { ApiClient } from "./types";
import { HttpApiClient } from "./httpClient";
import { MockApiClient } from "./mockClient";
import { PrecomputedApiClient } from "./precomputedClient";

// A real API tier now exists (api/interpret_handler.py, api/narrate_handler.py, behind
// CloudFront's /api/* — see infra/stacks/frontend_hosting_stack.py), but defaults still favor
// the fully-synthetic mock client until that deployment is confirmed working end to end — not a
// statement that it isn't real, just that flipping this default is a deliberate deploy-readiness
// decision, not something to change silently here. Three ways to opt in, checked in order:
// VITE_USE_PRECOMPUTED_API=true selects real process-stage output (see
// pipeline/climate_pipeline/process/, served at /precomputed/regions.json) with no backend
// required; VITE_USE_MOCK_API=false selects the real HTTP client, once ready to point at it.
const usePrecomputed = import.meta.env.VITE_USE_PRECOMPUTED_API === "true";
const useMock = import.meta.env.VITE_USE_MOCK_API !== "false";

export const apiClient: ApiClient = usePrecomputed
  ? new PrecomputedApiClient()
  : useMock
    ? new MockApiClient()
    : new HttpApiClient();

export type {
  ApiClient,
  ClarifyResumeRequest,
  ClimateMapPayload,
  Crop,
  MapCenter,
  NarrationResult,
  NarrationStatus,
  Provenance,
  QueryAnswer,
  QueryClarify,
  QueryInterpretation,
  QueryRefusal,
  QueryRequest,
  QueryResponse,
  RefusalReason,
  SectorMapPayload,
} from "./types";
