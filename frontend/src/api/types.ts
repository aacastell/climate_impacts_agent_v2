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

// Single climate model (GFDL-ESM4) — a single value, never a range. Framing
// this as a range or interval would fabricate an uncertainty estimate the
// data doesn't support.
export interface ClimateMapPayload {
  title: string;
  unit: string;
  value: number;
  center: MapCenter;
  zoom: number;
}

// Two crop models (pDSSAT, LPJmL) — always a range, never a mean or
// confidence interval. See README: "report the range, never a mean."
export interface SectorMapPayload {
  title: string;
  unit: string;
  range: [number, number];
  center: MapCenter;
  zoom: number;
}

export interface Provenance {
  dataVersion: string;
  indicatorVersion: string;
  climateModel: string;
  cropModels: string[];
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
