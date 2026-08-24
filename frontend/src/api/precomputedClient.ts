import type {
  ApiClient,
  ClimateIndicatorPayload,
  Crop,
  QueryAnswer,
  QueryRequest,
  QueryResponse,
} from "./types";
import { hashSeed, seededRandom } from "./deterministicRandom";
import { CROP_LABELS, findCrop, findRegion, findWarmingLevel } from "./questionParsing";

// Real precomputed values from the process stage (see
// pipeline/climate_pipeline/process/run.py), served as a static file through
// CloudFront (see infra/stacks/frontend_hosting_stack.py's /precomputed/*
// behavior) — never through a query API, since none exists yet (see repo
// README "Status" table). Region/crop parsing is still client-side, same as
// MockApiClient; the only thing that's real here is the numbers.

interface ProcessedWindow {
  gwl_c: number;
  center_year: number;
  tas_change: number;
  pr_change: number;
  maize_yield_change_pct: number;
  spring_wheat_yield_change_pct: number;
  soy_yield_change_pct: number;
  rice_yield_change_pct: number;
}

interface ProcessedRegion {
  name: string;
  lon: number;
  lat: number;
  windows: ProcessedWindow[];
}

interface ProcessedRegionsFile {
  regions: Record<string, ProcessedRegion>;
  provenance: {
    climate_model: string;
    scenario: string;
    crop_model: string;
    baseline_start_year: number;
    baseline_end_year: number;
    processed_at: string;
  };
}

// Crop -> the matching field name in a ProcessedWindow, set by
// process/run.py's f"{crop}_yield_change_pct" (crop is one of this
// project's own Crop identifiers, same vocabulary throughout).
const YIELD_FIELD: Record<Crop, keyof ProcessedWindow> = {
  maize: "maize_yield_change_pct",
  spring_wheat: "spring_wheat_yield_change_pct",
  soy: "soy_yield_change_pct",
  rice: "rice_yield_change_pct",
};

let cached: Promise<ProcessedRegionsFile> | null = null;

async function loadProcessedRegions(): Promise<ProcessedRegionsFile> {
  if (!cached) {
    cached = fetch("/precomputed/regions.json").then((res) => {
      if (!res.ok) {
        throw new Error(`Failed to load precomputed regions: ${res.status} ${res.statusText}`);
      }
      return res.json() as Promise<ProcessedRegionsFile>;
    });
  }
  return cached;
}

// The two indicators without a decided real computation yet — see
// pipeline/README.md's "stays synthetic for this pass" note. Kept separate
// from MockApiClient's version since only these two fields are still fake
// here; temp/precip/yield below come from the fetched file.
function syntheticDryDaysAndHeatDays(
  seedKey: string,
  warmingLevelC: number,
): { consecutiveDryDays: number; extremeHeatDays: number } {
  const rand = seededRandom(hashSeed(seedKey));
  return {
    consecutiveDryDays: Math.round(rand() * 5 * warmingLevelC),
    extremeHeatDays: Math.round(rand() * 8 * warmingLevelC),
  };
}

export class PrecomputedApiClient implements ApiClient {
  async submitQuery(request: QueryRequest): Promise<QueryResponse> {
    if (!request.question.trim()) {
      return {
        kind: "refusal",
        reason: "unparseable_question",
        message: "Ask a question naming a region, a crop, and a warming level.",
      };
    }

    const crop = findCrop(request.question);
    if (!crop) {
      return {
        kind: "refusal",
        reason: "unsupported_crop",
        message:
          "This system covers maize, spring wheat, soy, and rice only. Name one of those crops.",
      };
    }

    const region = findRegion(request.question);
    if (!region) {
      return {
        kind: "refusal",
        reason: "unsupported_region",
        message: "Name a region this demo recognizes, e.g. Occitanie, Iowa, or Punjab.",
      };
    }

    const requestedLevel = findWarmingLevel(request.question);
    const processed = await loadProcessedRegions();
    const processedRegion = processed.regions[region.slug];
    if (!processedRegion) {
      return {
        kind: "refusal",
        reason: "unsupported_region",
        message: `No precomputed data for ${region.name} yet.`,
      };
    }

    const matchedWindow =
      requestedLevel !== null
        ? processedRegion.windows.find((w) => w.gwl_c === requestedLevel)
        : undefined;
    if (!matchedWindow) {
      const available = processedRegion.windows.map((w) => `${w.gwl_c}°C`).join(", ");
      return {
        kind: "refusal",
        reason: "unsupported_warming_level",
        message: `State one of the warming levels this data actually covers for ${region.name}: ${available}.`,
      };
    }

    return this.buildAnswer(crop, region, matchedWindow, processed.provenance);
  }

  private buildAnswer(
    crop: Crop,
    region: { name: string; slug: string; center: { lon: number; lat: number } },
    matchedWindow: ProcessedWindow,
    provenance: ProcessedRegionsFile["provenance"],
  ): QueryAnswer {
    const { consecutiveDryDays, extremeHeatDays } = syntheticDryDaysAndHeatDays(
      `${region.slug}|${matchedWindow.gwl_c}`,
      matchedWindow.gwl_c,
    );

    const indicators: ClimateIndicatorPayload[] = [
      {
        id: "temp_change",
        title: `Local temperature change at ${matchedWindow.gwl_c}°C global warming`,
        unit: "°C",
        value: matchedWindow.tas_change,
      },
      {
        // TODO: this whole client reads a JSON shape from the old 5-region precompute output,
        // which no longer exists — the real process stage now writes per-(field,window) NetCDF
        // objects (processed/global/pr_abs/y{year}.nc, pr_pct/y{year}.nc, etc.), not a combined
        // regions.json. Renamed here only to keep this file type-checking against the current
        // ClimateIndicatorId union; not wired to the real output. Needs a real rewrite once a
        // query-time regional API exists to actually serve this shape. Not adding a
        // precip_change_pct entry here for the same reason — no sense building more on top of
        // an already-fictional interface.
        id: "precip_change_abs",
        title: `Local precipitation change at ${matchedWindow.gwl_c}°C global warming`,
        unit: "% precip change",
        value: matchedWindow.pr_change,
      },
      {
        id: "consecutive_dry_days",
        title: `Change in consecutive dry days at ${matchedWindow.gwl_c}°C global warming`,
        unit: "days",
        value: consecutiveDryDays,
      },
      {
        id: "extreme_heat_days",
        title: `Change in extreme heat days at ${matchedWindow.gwl_c}°C global warming`,
        unit: "days",
        value: extremeHeatDays,
      },
    ];

    const cropLabel = CROP_LABELS[crop];
    const yieldChange = matchedWindow[YIELD_FIELD[crop]];

    return {
      kind: "answer",
      interpretation: {
        region: region.name,
        crop,
        warmingLevelC: matchedWindow.gwl_c,
      },
      climateMap: {
        center: region.center,
        zoom: 5,
        indicators,
      },
      sectorMap: {
        title: `${cropLabel} yield change at ${matchedWindow.gwl_c}°C global warming`,
        unit: "% yield change",
        value: yieldChange,
        center: region.center,
        zoom: 5,
      },
      narration:
        `At ${matchedWindow.gwl_c}°C of global warming (around ${matchedWindow.center_year}), ${region.name} ` +
        `is projected to warm by about ${matchedWindow.tas_change}°C locally under ${provenance.scenario}, ` +
        `based on the ${provenance.climate_model} climate model. Non-irrigated ${cropLabel} yields ` +
        `in the region are projected to change by ${yieldChange}% relative to baseline, based on ` +
        `the ${provenance.crop_model} crop model.`,
      disclaimers: [
        "Management is frozen at 2015 conditions (2015soc) — no adaptation is represented.",
        "A single climate model provides no climate-model uncertainty range. The yield figure " +
          "comes from a single crop model (LPJmL) — pDSSAT is out of scope for this MVP (no " +
          "SSP3-7.0 output for GFDL-ESM4), so this is a point estimate, not a range or distribution.",
        "Consecutive dry days and extreme heat days are still placeholder values, not computed " +
          "from real data — see pipeline/README.md.",
      ],
      provenance: {
        dataVersion: provenance.processed_at,
        indicatorVersion: "process-v0",
        climateModel: provenance.climate_model,
        cropModel: provenance.crop_model,
        scenario: provenance.scenario,
        runSpecifier: "2015soc",
        promptVersion: "no-narration-model-yet",
      },
    };
  }
}
