import type { ApiClient } from "./types";
import { HttpApiClient } from "./httpClient";
import { MockApiClient } from "./mockClient";

// No API tier exists yet (see repo README "Status" table), so default to
// the mock client. Set VITE_USE_MOCK_API=false once a real endpoint exists.
const useMock = import.meta.env.VITE_USE_MOCK_API !== "false";

export const apiClient: ApiClient = useMock ? new MockApiClient() : new HttpApiClient();

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
