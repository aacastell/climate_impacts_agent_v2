import type { ApiClient, QueryRequest, QueryResponse } from "./types";

// Talks to the real API tier once one exists. Per ADR-001, the frontend and
// API are expected to share one CloudFront distribution under one domain
// (`/api/*`), so this deliberately uses a relative path rather than a
// configured base URL.
export class HttpApiClient implements ApiClient {
  async submitQuery(request: QueryRequest): Promise<QueryResponse> {
    const res = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });

    if (!res.ok) {
      throw new Error(`Query failed: ${res.status} ${res.statusText}`);
    }

    return (await res.json()) as QueryResponse;
  }
}
