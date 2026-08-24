import type { Crop, MapCenter } from "./types";

// Shared between MockApiClient (fully synthetic) and PrecomputedApiClient
// (real precomputed values, see process/regions.py) — there's still no real
// interpret API (see repo README "Status" table), so both clients resolve a
// question's crop/region client-side the same way.

export const CROP_KEYWORDS: Record<string, Crop> = {
  maize: "maize",
  corn: "maize",
  wheat: "spring_wheat",
  "spring wheat": "spring_wheat",
  soy: "soy",
  soybean: "soy",
  soybeans: "soy",
  rice: "rice",
};

export const CROP_LABELS: Record<Crop, string> = {
  maize: "maize",
  spring_wheat: "spring wheat",
  soy: "soy",
  rice: "rice",
};

// Must match pipeline/climate_pipeline/process/regions.py's REGIONS exactly
// (name, lon, lat) — see that module's docstring on why this is a
// deliberate duplication rather than a shared source of truth.
export const KNOWN_REGIONS: Record<string, MapCenter> = {
  occitanie: { lon: 2.15, lat: 43.6 },
  iowa: { lon: -93.6, lat: 42.0 },
  punjab: { lon: 75.3, lat: 31.1 },
  "nile delta": { lon: 31.0, lat: 30.8 },
  "mekong delta": { lon: 105.8, lat: 10.0 },
};

// Matches process/regions.py's dict keys (region slugs) — the identifiers
// PrecomputedApiClient uses to look up a region in the fetched JSON.
export const REGION_SLUGS: Record<string, string> = {
  occitanie: "occitanie",
  iowa: "iowa",
  punjab: "punjab",
  "nile delta": "nile_delta",
  "mekong delta": "mekong_delta",
};

export function findCrop(question: string): Crop | null {
  const lower = question.toLowerCase();
  for (const [keyword, crop] of Object.entries(CROP_KEYWORDS)) {
    if (lower.includes(keyword)) return crop;
  }
  return null;
}

export function findRegion(
  question: string,
): { name: string; slug: string; center: MapCenter } | null {
  const lower = question.toLowerCase();
  for (const [name, center] of Object.entries(KNOWN_REGIONS)) {
    if (lower.includes(name)) {
      return {
        name: name.replace(/\b\w/g, (c) => c.toUpperCase()),
        slug: REGION_SLUGS[name],
        center,
      };
    }
  }
  return null;
}

export function findWarmingLevel(question: string): number | null {
  const match = question.match(/(\d+(?:\.\d+)?)\s*°?\s*c\b/i);
  if (!match) return null;
  const level = Number.parseFloat(match[1]);
  return level > 0 && level <= 5 ? level : null;
}
