import type { ExpressionSpecification } from "@maplibre/maplibre-gl-style-spec";
import type { ClimateIndicatorId, GridPatch } from "./api/types";

// Per-indicator color language, not one shared amber-to-red for everything — each domain reads
// with its own real-world convention: precipitation as blues (wetter reads as deeper blue),
// extreme heat as reds, consecutive dry days as browns (more brown = more dryness), yield change
// as a diverging red-yellow-green (loss vs. gain), matching how these quantities are
// conventionally read elsewhere (meteorological precip anomaly maps, agricultural yield maps),
// not an arbitrary house style.

export interface ColorStop {
  value: number;
  /** Must be "hsl(h, s%, l%)" — every stop in this module uses this format so lerpHsl can parse
   * and interpolate it; a CSS named color or hex here would silently break interpolation. */
  color: string;
}

export interface ColorScale {
  /** Ascending by value, at least 2 entries. A 3-entry scale (yield) is diverging around its
   * middle stop; a 2-entry scale is sequential low-to-high. */
  stops: ColorStop[];
}

function parseHsl(css: string): [number, number, number] {
  const match = css.match(/hsl\(\s*(-?[\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*\)/);
  if (!match) throw new Error(`colorScales.ts stops must be "hsl(h, s%, l%)" strings, got "${css}"`);
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function lerpHsl(a: string, b: string, t: number): string {
  const [h1, s1, l1] = parseHsl(a);
  const [h2, s2, l2] = parseHsl(b);
  const clamped = Math.max(0, Math.min(1, t));
  const h = h1 + (h2 - h1) * clamped;
  const s = s1 + (s2 - s1) * clamped;
  const l = l1 + (l2 - l1) * clamped;
  return `hsl(${h}, ${s}%, ${l}%)`;
}

/** The real color for an arbitrary scalar (e.g. the resolved point's own exact value, which
 * rarely lands exactly on a grid cell or a stop) — used for the center marker, which is a plain
 * DOM element MapLibre's own paint-expression interpolation can't reach. */
export function colorAt(scale: ColorScale, value: number): string {
  const { stops } = scale;
  const first = stops[0];
  const last = stops[stops.length - 1];
  if (value <= first.value) return first.color;
  if (value >= last.value) return last.color;
  for (let i = 0; i < stops.length - 1; i++) {
    const a = stops[i];
    const b = stops[i + 1];
    if (value >= a.value && value <= b.value) {
      const span = b.value - a.value || 1;
      return lerpHsl(a.color, b.color, (value - a.value) / span);
    }
  }
  return last.color;
}

/** MapLibre does its own real-time interpolation in the paint expression (not this module's
 * lerpHsl) — this just tells it the same real stops, so the grid shading and colorAt() above
 * always agree on what a given value looks like. */
export function mapLibreFillExpression(scale: ColorScale, property = "value"): ExpressionSpecification {
  const stopArgs = scale.stops.flatMap((s) => [s.value, s.color]);
  return ["interpolate", ["linear"], ["get", property], ...stopArgs] as ExpressionSpecification;
}

/** CSS gradient for the legend swatch — stop positions are the real domain, not evenly spaced,
 * so a diverging scale's zero-stop lands wherever zero actually sits between its real min/max. */
export function cssGradient(scale: ColorScale): string {
  const { stops } = scale;
  const min = stops[0].value;
  const max = stops[stops.length - 1].value;
  const span = max - min || 1;
  const parts = stops.map((s) => `${s.color} ${(((s.value - min) / span) * 100).toFixed(1)}%`);
  return `linear-gradient(to right, ${parts.join(", ")})`;
}

// Sequential (low value -> high value), one 2-color palette per climate indicator.
const SEQUENTIAL_PALETTES: Record<ClimateIndicatorId, [low: string, high: string]> = {
  temp_change: ["hsl(40, 85%, 45%)", "hsl(0, 85%, 45%)"],
  precip_change_abs: ["hsl(200, 55%, 90%)", "hsl(215, 85%, 32%)"],
  precip_change_pct: ["hsl(200, 55%, 90%)", "hsl(215, 85%, 32%)"],
  extreme_heat_days: ["hsl(10, 70%, 90%)", "hsl(0, 85%, 35%)"],
  consecutive_dry_days: ["hsl(35, 55%, 88%)", "hsl(28, 60%, 28%)"],
};

export function colorScaleForIndicator(id: ClimateIndicatorId, domain: [number, number]): ColorScale {
  const [low, high] = SEQUENTIAL_PALETTES[id];
  const [min, max] = domain;
  return { stops: [{ value: min, color: low }, { value: max, color: high }] };
}

const YIELD_NEGATIVE = "hsl(0, 70%, 45%)"; // loss
const YIELD_ZERO = "hsl(50, 90%, 55%)";
const YIELD_POSITIVE = "hsl(140, 55%, 38%)"; // gain

/** Diverging, symmetric around zero — a loss and a gain of the same magnitude get equally
 * saturated colors on opposite ends, which a plain [min, max] sequential domain wouldn't
 * guarantee (a patch skewed toward losses would make small gains look disproportionately faint). */
export function colorScaleForYield(maxAbsValue: number): ColorScale {
  const m = maxAbsValue || 1; // degenerate all-zero guard, not a real case to over-think
  return {
    stops: [
      { value: -m, color: YIELD_NEGATIVE },
      { value: 0, color: YIELD_ZERO },
      { value: m, color: YIELD_POSITIVE },
    ],
  };
}

function realGridValues(grid: GridPatch): number[] {
  return grid.values.flat().filter((v): v is number => v !== null);
}

/** The real [min, max] a grid's own non-null cells span — null when every cell was null (all
 * ocean/masked-land patch), which callers fall back from, not something this fabricates a value
 * for. Widens a degenerate single-value domain so downstream interpolation never divides by
 * zero. */
export function gridDomain(grid: GridPatch): [number, number] | null {
  const values = realGridValues(grid);
  if (values.length === 0) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  return min === max ? [min - 1, max + 1] : [min, max];
}

/** The real largest-magnitude value in a grid's non-null cells — the diverging yield scale's
 * symmetric domain input. 1 when every cell was null, matching colorScaleForYield's own guard. */
export function gridMaxAbs(grid: GridPatch): number {
  const values = realGridValues(grid);
  if (values.length === 0) return 1;
  return Math.max(...values.map((v) => Math.abs(v))) || 1;
}
