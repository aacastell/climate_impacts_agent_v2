// API contract for the query endpoint. The API tier itself is not yet decided
// (see repo README "Status" table) — this is the shape the frontend needs,
// not a shape any backend has committed to.

export type Crop = "maize" | "spring_wheat" | "soy" | "rice";

export interface QueryRequest {
  question: string;
}

export interface QueryInterpretation {
  region: string;
  crop: Crop;
  warmingLevelC: number;
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

export interface QueryAnswer {
  kind: "answer";
  interpretation: QueryInterpretation;
  climateMap: ClimateMapPayload;
  sectorMap: SectorMapPayload;
  narration: string;
  // Always includes the two mandatory facts from the README: no adaptation
  // represented (2015soc), and no climate-model uncertainty range.
  disclaimers: string[];
  provenance: Provenance;
}

// Refusals are typed and deterministic, never a model judgement call — see
// README "Conventions". A high refusal rate is accepted, not a defect.
export type RefusalReason =
  | "unsupported_crop"
  | "unsupported_region"
  | "unsupported_warming_level"
  | "ambiguous_question"
  | "unparseable_question";

export interface QueryRefusal {
  kind: "refusal";
  reason: RefusalReason;
  message: string;
}

export type QueryResponse = QueryAnswer | QueryRefusal;

export interface ApiClient {
  submitQuery(request: QueryRequest): Promise<QueryResponse>;
}
