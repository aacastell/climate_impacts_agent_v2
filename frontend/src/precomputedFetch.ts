import { ready, FS, File as H5File } from "h5wasm";
import type { Dataset } from "h5wasm";
import type { GridPatch } from "./api/types";

// ADR-004's restored decision: the backend never computes a scientific value — it returns real
// identifiers (outputField, year) and this module fetches the matching precomputed file directly
// from the same CloudFront distribution (see infra/stacks/frontend_hosting_stack.py's
// /processed/* behavior — already live, no new infra needed) and parses it itself. Real HDF5/
// NetCDF4 files (confirmed live: `file` on a real sample reports "Hierarchical Data Format
// (version 5) data", not classic NetCDF3, ruling out netcdfjs-style parsers) — h5wasm is a real
// WebAssembly build of the actual HDF5 C library (NIST, actively maintained), not a toy.
//
// Real, confirmed-live file layout (via h5py against a real fetched sample, not assumed): flat
// root-level datasets "lat" (360 floats), "lon" (720 floats), and the field itself (360x720,
// row-major, dims [lat, lon]) — no nested groups. _FillValue is NaN itself, not a sentinel
// number, so a plain NaN check is the correct and only masking rule needed.

let readyPromise: Promise<unknown> | null = null;
function h5Ready(): Promise<unknown> {
  if (!readyPromise) readyPromise = ready;
  return readyPromise;
}

// 1 kg/m^2 of water = 1mm depth; pr is stored in the canonical store as a per-second flux (CF/
// ISIMIP convention, kg m-2 s-1) — converting to the human-readable mm/day the frontend displays
// is a presentation-layer concern, same real conversion the backend used to do server-side
// before this moved client-side.
const KG_M2_S1_TO_MM_PER_DAY = 86400.0;

// Same real-world-meaningful box the backend used before this moved client-side (≈220km at the
// equator, real ISIMIP 0.5° cells) — not an arbitrary pixel count.
const GRID_RADIUS_DEG = 2.0;

function round4(value: number): number {
  return Math.round(value * 10000) / 10000;
}

function nearestIndex(coords: Float64Array, target: number): number {
  let best = 0;
  let bestDist = Infinity;
  for (let i = 0; i < coords.length; i++) {
    const d = Math.abs(coords[i] - target);
    if (d < bestDist) {
      bestDist = d;
      best = i;
    }
  }
  return best;
}

export interface PrecomputedField {
  value: number;
  grid: GridPatch;
}

let fileCounter = 0;

/** Fetches processed/global/{outputField}/y{year}.nc directly from CloudFront (same origin —
 * no CORS needed, per ADR-001) and parses it with h5wasm — the real client-side counterpart to
 * pipeline/climate_pipeline/query/lookup.py's lookup_value/grid_patch, which used to run
 * server-side before ADR-004 was restored. */
export async function fetchPrecomputedField(
  outputField: string,
  year: number,
  lon: number,
  lat: number,
): Promise<PrecomputedField> {
  await h5Ready();

  const response = await fetch(`/processed/global/${outputField}/y${year}.nc`);
  if (!response.ok) {
    throw new Error(`Failed to fetch precomputed field ${outputField}/y${year}: ${response.status}`);
  }
  const buffer = await response.arrayBuffer();

  const virtualName = `field-${fileCounter++}.nc`;
  FS!.writeFile(virtualName, new Uint8Array(buffer));
  const file = new H5File(virtualName, "r");
  try {
    // .get() returns the Entity union (Dataset | Group | ...) — real cast, not a type-checking
    // workaround: these three paths are always plain root-level Datasets in this pipeline's own
    // output (confirmed live via h5py against a real fetched file), never Groups.
    const lats = (file.get("lat") as Dataset).value as Float64Array;
    const lons = (file.get("lon") as Dataset).value as Float64Array;
    const raw = (file.get(outputField) as Dataset).value as Float32Array;
    const nlon = lons.length;

    const isPrAbs = outputField === "pr_abs";
    const convert = isPrAbs ? (v: number) => v * KG_M2_S1_TO_MM_PER_DAY : (v: number) => v;

    const latIdx = nearestIndex(lats, lat);
    const lonIdx = nearestIndex(lons, lon);
    const value = round4(convert(raw[latIdx * nlon + lonIdx]));

    const latIndices: number[] = [];
    for (let i = 0; i < lats.length; i++) {
      if (Math.abs(lats[i] - lat) <= GRID_RADIUS_DEG) latIndices.push(i);
    }
    const lonIndices: number[] = [];
    for (let j = 0; j < nlon; j++) {
      if (Math.abs(lons[j] - lon) <= GRID_RADIUS_DEG) lonIndices.push(j);
    }

    const gridLats = latIndices.map((i) => lats[i]);
    const gridLons = lonIndices.map((j) => lons[j]);
    const values: (number | null)[][] = latIndices.map((i) =>
      lonIndices.map((j) => {
        const rawValue = raw[i * nlon + j];
        return Number.isNaN(rawValue) ? null : round4(convert(rawValue));
      }),
    );

    return { value, grid: { lons: gridLons, lats: gridLats, values } };
  } finally {
    file.close();
    FS!.unlink(virtualName);
  }
}

/** Real, confirmed-live gap this ports from the backend: climate fields (tas/pr/etc.) cover
 * every land cell, but a crop's real ISIMIP-modeled yield only exists where that crop is
 * actually grown — LPJmL's own output is null outside it. Masks a climate field's grid to the
 * same real cells the crop's own yield grid already covers. Safe to index cell-for-cell: both
 * come from the same global grid at the same (lon, lat, radius), so their coordinate arrays are
 * always identical. */
export function applyCropMask(field: PrecomputedField, yieldField: PrecomputedField): PrecomputedField {
  return {
    value: field.value,
    grid: {
      ...field.grid,
      values: field.grid.values.map((row, i) =>
        row.map((v, j) => (yieldField.grid.values[i]?.[j] === null ? null : v)),
      ),
    },
  };
}
