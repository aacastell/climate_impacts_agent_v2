// API contract for the query endpoint. Matches the real backend now that one exists
// (api/interpret_handler.py, api/narrate_handler.py) — interpret() and narrate() are two
// separate calls (ADR-004 Step 4: narrate() is a pure function of the interpretation, never
// receives anything interpret() computed), and clarify() is a real, resumable round-trip
// (ADR-005's query_id/session-store design), not just a dead-end message.

export type Crop = "maize" | "spring_wheat" | "soy" | "rice";

export interface QueryRequest {
  question: string;
}

// A follow-up answering a clarify() prompt — carries the session's query_id back so the backend
// can resume the stored conversation instead of starting a fresh one. See
// api/interpret_handler.py's session store.
export interface ClarifyResumeRequest {
  queryId: string;
  answer: string;
}

export interface QueryInterpretation {
  region: string;
  regionLon: number;
  regionLat: number;
  crop: Crop;
  warmingLevelC: number;
  year: number;
}

export interface MapCenter {
  lon: number;
  lat: number;
}

// Several climate indicators can describe the same region/warming level —
// temperature change, precipitation change, consecutive dry-day change, and
// others as scientific scope expands (see ADR-004). The frontend toggles
// between them client-side; all of them arrive in the same response, since
// per ADR-004 the underlying grids are precomputed and small relative to a
// single resolved region, not fetched or computed per toggle.
//
// precip_change_abs/precip_change_pct, not one "precip_change": percent change is only valid
// for continuous quantities with a true zero where it's the domain-conventional framing, and
// even then a small-baseline cell can make it technically correct but misleading (arid regions)
// — so both are shown, not one picked on the data's behalf. temp_change has no percent
// counterpart at all: temperature has no true zero, so percent change is invalid, not just
// unhelpful. Matches the same distinction the backend's process stage makes (see
// pipeline/README.md's "Not every field gets a single output" section).
export type ClimateIndicatorId =
  | "temp_change"
  | "precip_change_abs"
  | "precip_change_pct"
  | "consecutive_dry_days"
  | "extreme_heat_days";

// Single climate model (GFDL-ESM4) — a single value per indicator, never a
// range. Framing this as a range or interval would fabricate an uncertainty
// estimate the data doesn't support.
export interface ClimateIndicatorPayload {
  id: ClimateIndicatorId;
  title: string;
  unit: string;
  value: number;
}

export interface ClimateMapPayload {
  center: MapCenter;
  zoom: number;
  indicators: ClimateIndicatorPayload[];
}

// A single crop model (LPJmL) — a single value, never a range. pDSSAT was
// dropped for this MVP (no SSP3-7.0 output for GFDL-ESM4 — see repo root
// README Scope section), leaving nothing to range LPJmL's output against.
// Framing a single model's output as a range would fabricate an uncertainty
// estimate the data doesn't support — the same rule ADR-004 already states
// for climate indicators, applied here to yield.
export interface SectorMapPayload {
  title: string;
  unit: string;
  value: number;
  center: MapCenter;
  zoom: number;
}

export interface Provenance {
  dataVersion: string;
  indicatorVersion: string;
  climateModel: string;
  cropModel: string;
  scenario: string;
  runSpecifier: string;
  promptVersion: string;
}

// Narration is fetched separately from the answer (ApiClient.fetchNarration), never bundled
// into QueryAnswer — it's a genuinely slower, independent call in the real backend (RAG +
// generation + verification, with up to 2 retries), and the UI shows the maps immediately while
// narration is still loading rather than blocking on the slowest part of the response.
export type NarrationStatus = "PASS" | "SCIENTIFIC_DISAGREEMENT";

export interface NarrationResult {
  narration: string;
  status: NarrationStatus;
  attempts: number;
}

export interface QueryAnswer {
  kind: "answer";
  interpretation: QueryInterpretation;
  climateMap: ClimateMapPayload;
  sectorMap: SectorMapPayload;
  // Always includes the two mandatory facts from the README: no adaptation
  // represented (2015soc), and no climate-model uncertainty range.
  disclaimers: string[];
  provenance: Provenance;
}

// The model asked for clarification instead of guessing (see
// services/understanding/orchestrator.py's SYSTEM_PROMPT) — queryId must be sent back with the
// user's answer via ApiClient.submitClarifyAnswer to resume the same conversation; it is not a
// new question and re-sending the original text alone would lose everything the model already
// resolved.
export interface QueryClarify {
  kind: "clarify";
  queryId: string;
  question: string;
}

// Refusals are typed and deterministic, never a model judgement call — see
// README "Conventions". A high refusal rate is accepted, not a defect.
export type RefusalReason =
  | "unsupported_crop"
  | "unsupported_region"
  | "unsupported_warming_level"
  | "ambiguous_question"
  | "unparseable_question"
  | "no_resolution"
  | "session_expired";

export interface QueryRefusal {
  kind: "refusal";
  reason: RefusalReason;
  message: string;
}

export type QueryResponse = QueryAnswer | QueryClarify | QueryRefusal;

export interface ApiClient {
  submitQuery(request: QueryRequest): Promise<QueryResponse>;
  // Resumes a clarify() round-trip. Clients that never emit QueryClarify (MockApiClient,
  // PrecomputedApiClient) are not required to make this reachable — see their implementations.
  submitClarifyAnswer(resume: ClarifyResumeRequest): Promise<QueryResponse>;
  fetchNarration(interpretation: QueryInterpretation): Promise<NarrationResult>;
}
