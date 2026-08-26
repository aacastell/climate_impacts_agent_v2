import type { ApiClient } from "./types";
import { HttpApiClient } from "./httpClient";
import { MockApiClient } from "./mockClient";

// A real, deployed, verified end-to-end API tier exists (api/interpret_handler.py,
// api/narrate_handler.py, behind CloudFront's /api/* — see infra/stacks/frontend_hosting_stack.py)
// — VITE_USE_MOCK_API=false selects it. Defaults to the fully-synthetic mock client for local
// dev without a deployed backend. (PrecomputedApiClient, an earlier third option reading
// process-stage output directly, was removed — it depended on a /precomputed/regions.json route
// that was never actually provisioned; see docs/roadmap.md Phase 4's own note on retiring it.)
const useMock = import.meta.env.VITE_USE_MOCK_API !== "false";

export const apiClient: ApiClient = useMock ? new MockApiClient() : new HttpApiClient();

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
