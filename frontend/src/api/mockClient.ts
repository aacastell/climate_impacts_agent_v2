import type {
  ApiClient,
  ClimateIndicatorPayload,
  Crop,
  MapCenter,
  NarrationResult,
  QueryAnswer,
  QueryInterpretation,
  QueryRequest,
  QueryResponse,
} from "./types";
import { hashSeed, seededRandom } from "./deterministicRandom";
import { CROP_LABELS, findCrop, findRegion, findWarmingLevel } from "./questionParsing";

// Stands in for the API tier, which is not yet decided (see repo README
// "Status" table). Parses just enough of the question to demonstrate the
// UI end to end with plausible, deterministic data. None of the numbers
// here are real ISIMIP output — see PrecomputedApiClient for the real-data
// counterpart, once process-stage output actually exists.

function buildClimateIndicators(
  warmingLevelC: number,
  rand: () => number,
): ClimateIndicatorPayload[] {
  const tempChange = Number((warmingLevelC * (1.1 + rand() * 0.6)).toFixed(1));
  // Synthetic, not a real precip response — some regions dry, some wet, both
  // plausible under warming, so this can land on either side of zero.
  const precipChangePct = Number(((rand() - 0.5) * 10 * warmingLevelC).toFixed(1));
  // Synthetic mm/day counterpart — same sign as the percent figure (a demo shouldn't show precip
  // rising in % but falling in mm), independently scaled magnitude. Two fields, not one: percent
  // change is only valid for a continuous ratio-scale quantity with a true zero, and even then a
  // small baseline can make it technically-correct-but-misleading — see types.ts.
  const precipChangeAbs = Number((Math.sign(precipChangePct) * rand() * 2 * warmingLevelC).toFixed(2));
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
      id: "precip_change_abs",
      title: `Local precipitation change at ${warmingLevelC}°C global warming`,
      unit: "mm/day",
      value: precipChangeAbs,
    },
    {
      id: "precip_change_pct",
      title: `Local precipitation change at ${warmingLevelC}°C global warming`,
      unit: "% precip change",
      value: precipChangePct,
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

  // Never actually reachable — MockApiClient only ever returns "answer" or "refusal" from
  // submitQuery, never "clarify" — but the ApiClient interface requires every implementation to
  // support resuming one, since the real HttpApiClient does. Failing loudly here is correct if
  // this ever somehow gets called; a silent fallback would hide a real bug in the caller.
  async submitClarifyAnswer(): Promise<QueryResponse> {
    throw new Error("MockApiClient never emits clarify() — submitClarifyAnswer is unreachable.");
  }

  async fetchNarration(interpretation: QueryInterpretation): Promise<NarrationResult> {
    await new Promise((resolve) => setTimeout(resolve, 500));
    const { tempChange, yieldChange, cropLabel } = this.deterministicValues(
      interpretation.crop,
      interpretation.region,
      interpretation.warmingLevelC,
    );
    return {
      narration:
        `At ${interpretation.warmingLevelC}°C of global warming, ${interpretation.region} is projected to warm by about ` +
        `${tempChange}°C locally under SSP3-7.0, based on the GFDL-ESM4 climate model. ` +
        `Non-irrigated ${cropLabel} yields in the region are projected to change by ` +
        `${yieldChange}% relative to baseline, based on the LPJmL crop model.`,
      status: "PASS",
      attempts: 1,
    };
  }

  // Shared by buildAnswer and fetchNarration so both derive the same tempChange/yieldChange from
  // the same seed — narration always agrees with the maps it's describing, without the two
  // being computed together in one call (mirrors the real backend's two-independent-calls shape).
  private deterministicValues(crop: Crop, regionName: string, warmingLevelC: number) {
    const rand = seededRandom(hashSeed(`${regionName}|${crop}|${warmingLevelC}`));
    const indicators = buildClimateIndicators(warmingLevelC, rand);
    const tempChange = indicators[0].value;
    const yieldChange = Number((-(warmingLevelC * (3 + rand() * 4))).toFixed(1));
    return { indicators, tempChange, yieldChange, cropLabel: CROP_LABELS[crop] };
  }

  private buildAnswer(
    crop: Crop,
    region: { name: string; center: MapCenter },
    warmingLevelC: number,
  ): QueryAnswer {
    const { indicators, yieldChange, cropLabel } = this.deterministicValues(crop, region.name, warmingLevelC);

    return {
      kind: "answer",
      interpretation: {
        region: region.name,
        regionLon: region.center.lon,
        regionLat: region.center.lat,
        crop,
        warmingLevelC,
        // No real year concept in this synthetic client — a plausible-looking value in the
        // real system's actual range (2025-2091, see warming_levels.py), not derived from data.
        year: Math.round(2025 + warmingLevelC * 20),
      },
      climateMap: {
        center: region.center,
        zoom: 5,
        indicators,
      },
      sectorMap: {
        title: `${cropLabel} yield change at ${warmingLevelC}°C global warming`,
        unit: "% yield change",
        value: yieldChange,
        center: region.center,
        zoom: 5,
      },
      disclaimers: [
        "Management is frozen at 2015 conditions (2015soc) — no adaptation is represented.",
        "A single climate model provides no climate-model uncertainty range. The yield figure " +
          "comes from a single crop model (LPJmL) — pDSSAT is out of scope for this MVP (no " +
          "SSP3-7.0 output for GFDL-ESM4), so this is a point estimate, not a range or distribution.",
      ],
      provenance: {
        dataVersion: "mock-data-0",
        indicatorVersion: "mock-indicator-0",
        climateModel: "GFDL-ESM4",
        cropModel: "LPJmL",
        scenario: "SSP3-7.0",
        runSpecifier: "2015soc",
        promptVersion: "mock-prompt-0",
      },
    };
  }
}
