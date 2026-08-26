import type { Crop, MapCenter } from "./types";

// Used by MockApiClient to resolve a question's crop/region client-side, without a real backend.

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

// The 5 demo regions MockApiClient recognizes — real coordinates, synthetic everything else
// about the response.
export const KNOWN_REGIONS: Record<string, MapCenter> = {
  occitanie: { lon: 2.15, lat: 43.6 },
  iowa: { lon: -93.6, lat: 42.0 },
  punjab: { lon: 75.3, lat: 31.1 },
  "nile delta": { lon: 31.0, lat: 30.8 },
  "mekong delta": { lon: 105.8, lat: 10.0 },
};

export function findCrop(question: string): Crop | null {
  const lower = question.toLowerCase();
  for (const [keyword, crop] of Object.entries(CROP_KEYWORDS)) {
    if (lower.includes(keyword)) return crop;
  }
  return null;
}

export function findRegion(question: string): { name: string; center: MapCenter } | null {
  const lower = question.toLowerCase();
  for (const [name, center] of Object.entries(KNOWN_REGIONS)) {
    if (lower.includes(name)) {
      return { name: name.replace(/\b\w/g, (c) => c.toUpperCase()), center };
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
