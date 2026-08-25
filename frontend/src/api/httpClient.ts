import type {
  ApiClient,
  ClarifyResumeRequest,
  ClimateMapPayload,
  NarrationResult,
  Provenance,
  QueryInterpretation,
  QueryRequest,
  QueryResponse,
  RefusalReason,
  SectorMapPayload,
} from "./types";

// Talks to the real API tier (api/interpret_handler.py, api/narrate_handler.py) behind the same
// CloudFront distribution as the frontend itself (see infra/stacks/frontend_hosting_stack.py's
// /api/* behavior) — a relative path, per ADR-001, so this is always a same-origin request with
// no CORS configuration needed anywhere.

interface RawInterpretResponse {
  kind: "answer" | "clarify" | "refusal";
  // answer
  interpretation?: {
    region: string;
    region_lon: number;
    region_lat: number;
    crop: string;
    warmingLevelC: number;
    year: number;
  };
  climateMap?: ClimateMapPayload;
  sectorMap?: SectorMapPayload;
  disclaimers?: string[];
  provenance?: Provenance;
  // clarify
  query_id?: string;
  question?: string;
  // refusal
  reason?: string;
  message?: string;
}

interface RawNarrateResponse {
  narration: string;
  status: "PASS" | "SCIENTIFIC_DISAGREEMENT";
  attempts: number;
}

function toQueryResponse(raw: RawInterpretResponse): QueryResponse {
  if (raw.kind === "clarify") {
    return { kind: "clarify", queryId: raw.query_id!, question: raw.question! };
  }
  if (raw.kind === "refusal") {
    return {
      kind: "refusal",
      reason: (raw.reason as RefusalReason) ?? "unparseable_question",
      message: raw.message ?? "Could not resolve the question.",
    };
  }
  const i = raw.interpretation!;
  return {
    kind: "answer",
    interpretation: {
      region: i.region,
      regionLon: i.region_lon,
      regionLat: i.region_lat,
      crop: i.crop as QueryInterpretation["crop"],
      warmingLevelC: i.warmingLevelC,
      year: i.year,
    },
    // climateMap/sectorMap/disclaimers/provenance already match the frontend's own shape field
    // for field — api/interpret_handler.py was written against this exact contract (ADR-004).
    climateMap: raw.climateMap!,
    sectorMap: raw.sectorMap!,
    disclaimers: raw.disclaimers ?? [],
    provenance: raw.provenance!,
  };
}

export class HttpApiClient implements ApiClient {
  async submitQuery(request: QueryRequest): Promise<QueryResponse> {
    const res = await fetch("/api/interpret", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: request.question }),
    });
    if (!res.ok) {
      throw new Error(`Query failed: ${res.status} ${res.statusText}`);
    }
    return toQueryResponse((await res.json()) as RawInterpretResponse);
  }

  async submitClarifyAnswer(resume: ClarifyResumeRequest): Promise<QueryResponse> {
    const res = await fetch("/api/interpret", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // question is required by the backend's request shape but ignored whenever query_id is
      // present (see api/interpret_handler.py) — the stored original question is used instead.
      body: JSON.stringify({ question: "", query_id: resume.queryId, answer: resume.answer }),
    });
    if (!res.ok) {
      throw new Error(`Query failed: ${res.status} ${res.statusText}`);
    }
    return toQueryResponse((await res.json()) as RawInterpretResponse);
  }

  async fetchNarration(interpretation: QueryInterpretation): Promise<NarrationResult> {
    const res = await fetch("/api/narrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        interpretation: {
          region: interpretation.region,
          region_lon: interpretation.regionLon,
          region_lat: interpretation.regionLat,
          crop: interpretation.crop,
          warmingLevelC: interpretation.warmingLevelC,
          year: interpretation.year,
        },
      }),
    });
    if (!res.ok) {
      throw new Error(`Narration failed: ${res.status} ${res.statusText}`);
    }
    const raw = (await res.json()) as RawNarrateResponse;
    return { narration: raw.narration, status: raw.status, attempts: raw.attempts };
  }
}
