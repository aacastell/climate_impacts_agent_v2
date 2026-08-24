// Small deterministic PRNG: same seed string always produces the same
// sequence, so demo output stays stable across requests/renders without
// needing a real backend to persist anything. Shared by MockApiClient (all
// four climate indicators) and PrecomputedApiClient (the two indicators —
// consecutive_dry_days, extreme_heat_days — that stay synthetic until a
// real climate-index methodology is decided; see pipeline/README.md).

export function hashSeed(input: string): number {
  let h = 0;
  for (let i = 0; i < input.length; i++) {
    h = (h * 31 + input.charCodeAt(i)) >>> 0;
  }
  return h;
}

export function seededRandom(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1103515245 + 12345) >>> 0;
    return state / 0xffffffff;
  };
}
