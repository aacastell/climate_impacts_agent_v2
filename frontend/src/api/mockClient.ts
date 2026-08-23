import type {
  ApiClient,
  ClimateIndicatorPayload,
  Crop,
  MapCenter,
  QueryAnswer,
  QueryRequest,
  QueryResponse,
} from "./types";

// Stands in for the API tier, which is not yet decided (see repo README
// "Status" table). Parses just enough of the question to demonstrate the
// UI end to end with plausible, deterministic data. None of the numbers
// here are real ISIMIP output.

const CROP_KEYWORDS: Record<string, Crop> = {
  maize: "maize",
  corn: "maize",
  wheat: "spring_wheat",
  "spring wheat": "spring_wheat",
  soy: "soy",
  soybean: "soy",
  soybeans: "soy",
  rice: "rice",
};

const KNOWN_REGIONS: Record<string, MapCenter> = {
  occitanie: { lon: 2.15, lat: 43.6 },
  iowa: { lon: -93.6, lat: 42.0 },
  punjab: { lon: 75.3, lat: 31.1 },
  "nile delta": { lon: 31.0, lat: 30.8 },
  "mekong delta": { lon: 105.8, lat: 10.0 },
};

function hashSeed(input: string): number {
  let h = 0;
  for (let i = 0; i < input.length; i++) {
    h = (h * 31 + input.charCodeAt(i)) >>> 0;
  }
  return h;
}

function seededRandom(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1103515245 + 12345) >>> 0;
    return state / 0xffffffff;
  };
}

function findCrop(question: string): Crop | null {
  const lower = question.toLowerCase();
  for (const [keyword, crop] of Object.entries(CROP_KEYWORDS)) {
    if (lower.includes(keyword)) return crop;
  }
  return null;
}

function findRegion(question: string): { name: string; center: MapCenter } | null {
  const lower = question.toLowerCase();
  for (const [name, center] of Object.entries(KNOWN_REGIONS)) {
    if (lower.includes(name)) {
      return { name: name.replace(/\b\w/g, (c) => c.toUpperCase()), center };
    }
  }
  return null;
}

function findWarmingLevel(question: string): number | null {
  const match = question.match(/(\d+(?:\.\d+)?)\s*°?\s*c\b/i);
  if (!match) return null;
  const level = Number.parseFloat(match[1]);
  return level > 0 && level <= 5 ? level : null;
}

function buildClimateIndicators(
  warmingLevelC: number,
  rand: () => number,
): ClimateIndicatorPayload[] {
  const tempChange = Number((warmingLevelC * (1.1 + rand() * 0.6)).toFixed(1));
  // Synthetic, not a real precip response — some regions dry, some wet, both
  // plausible under warming, so this can land on either side of zero.
  const precipChange = Number(((rand() - 0.5) * 10 * warmingLevelC).toFixed(1));
  // Dry-day counts trend up with warming in this synthetic model; never
  // negative, since "fewer dry days" isn't the story this mock is telling.
  const consecutiveDryDays = Math.round(rand() * 5 * warmingLevelC);
  // Extreme-heat-day counts respond more steeply to warming than dry days
  // in this synthetic model — still never negative, same reasoning.
  const extremeHeatDays = Math.round(rand() * 8 * warmingLevelC);

  return [
    {
      id: "temp_change",
      title: `Local temperature change at ${warmingLevelC}°C global warming`,
      unit: "°C",
      value: tempChange,
    },
    {
      id: "precip_change",
      title: `Local precipitation change at ${warmingLevelC}°C global warming`,
      unit: "% precip change",
      value: precipChange,
    },
    {
      id: "consecutive_dry_days",
      title: `Change in consecutive dry days at ${warmingLevelC}°C global warming`,
      unit: "days",
      value: consecutiveDryDays,
    },
    {
      id: "extreme_heat_days",
      title: `Change in extreme heat days at ${warmingLevelC}°C global warming`,
      unit: "days",
      value: extremeHeatDays,
    },
  ];
}

const CROP_LABELS: Record<Crop, string> = {
  maize: "maize",
  spring_wheat: "spring wheat",
  soy: "soy",
  rice: "rice",
};

export class MockApiClient implements ApiClient {
  async submitQuery(request: QueryRequest): Promise<QueryResponse> {
    // Simulate network latency so loading states are visible.
    await new Promise((resolve) => setTimeout(resolve, 500));

    const crop = findCrop(request.question);
    const region = findRegion(request.question);
    const warmingLevelC = findWarmingLevel(request.question);

    if (!request.question.trim()) {
      return {
        kind: "refusal",
        reason: "unparseable_question",
        message: "Ask a question naming a region, a crop, and a warming level.",
      };
    }
    if (!crop) {
      return {
        kind: "refusal",
        reason: "unsupported_crop",
        message:
          "This system covers maize, spring wheat, soy, and rice only. Name one of those crops.",
      };
    }
    if (!region) {
      return {
        kind: "refusal",
        reason: "unsupported_region",
        message: "Name a region this demo recognizes, e.g. Occitanie, Iowa, or Punjab.",
      };
    }
    if (warmingLevelC === null) {
      return {
        kind: "refusal",
        reason: "unsupported_warming_level",
        message: "State a global warming level between 1°C and 5°C, e.g. \"at 2°C\".",
      };
    }

    return this.buildAnswer(crop, region, warmingLevelC);
  }

  private buildAnswer(
    crop: Crop,
    region: { name: string; center: MapCenter },
    warmingLevelC: number,
  ): QueryAnswer {
    const rand = seededRandom(hashSeed(`${region.name}|${crop}|${warmingLevelC}`));

    const indicators = buildClimateIndicators(warmingLevelC, rand);
    const tempChange = indicators[0].value;

    const yieldCenter = -(warmingLevelC * (3 + rand() * 4));
    const spread = 4 + rand() * 6;
    const sectorRange: [number, number] = [
      Number((yieldCenter - spread / 2).toFixed(1)),
      Number((yieldCenter + spread / 2).toFixed(1)),
    ];

    const cropLabel = CROP_LABELS[crop];

    return {
      kind: "answer",
      interpretation: {
        region: region.name,
        crop,
        warmingLevelC,
      },
      climateMap: {
        center: region.center,
        zoom: 5,
        indicators,
      },
      sectorMap: {
        title: `${cropLabel} yield change at ${warmingLevelC}°C global warming`,
        unit: "% yield change",
        range: sectorRange,
        center: region.center,
        zoom: 5,
      },
      narration:
        `At ${warmingLevelC}°C of global warming, ${region.name} is projected to warm by about ` +
        `${tempChange}°C locally under SSP3-7.0, based on the GFDL-ESM4 climate model. ` +
        `Non-irrigated ${cropLabel} yields in the region are projected to change by ` +
        `${sectorRange[0]}% to ${sectorRange[1]}% relative to baseline, reflecting the spread ` +
        `between the pDSSAT and LPJmL crop models.`,
      disclaimers: [
        "Management is frozen at 2015 conditions (2015soc) — no adaptation is represented.",
        "A single climate model provides no climate-model uncertainty range. The yield figure " +
          "is a range between two crop models, not a distribution — it has no mean or confidence interval.",
      ],
      provenance: {
        dataVersion: "mock-data-0",
        indicatorVersion: "mock-indicator-0",
        climateModel: "GFDL-ESM4",
        cropModels: ["pDSSAT", "LPJmL"],
        scenario: "SSP3-7.0",
        runSpecifier: "2015soc",
        promptVersion: "mock-prompt-0",
      },
    };
  }
}
