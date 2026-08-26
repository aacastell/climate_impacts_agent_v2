import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { Map as MapLibreMap, Marker, NavigationControl, setWorkerUrl } from "maplibre-gl";
import type { GeoJSONSource } from "maplibre-gl";
import type { Feature, FeatureCollection } from "geojson";
import "maplibre-gl/dist/maplibre-gl.css";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import type { ExpressionSpecification, StyleSpecification } from "@maplibre/maplibre-gl-style-spec";
import type { MapCenter, GridPatch } from "../api/types";
import "./ResultMap.css";

const GRID_SOURCE_ID = "indicator-grid";
const GRID_LAYER_ID = "indicator-grid-fill";

// Same amber-to-red hue sweep as markerColor() below, expressed as a MapLibre paint expression
// so the region shading and the center marker always read as one consistent color language, not
// two different scales that happen to share a name.
const GRID_FILL_COLOR: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["get", "norm"],
  0,
  "hsl(40, 85%, 45%)",
  1,
  "hsl(0, 85%, 45%)",
];

const EMPTY_FEATURE_COLLECTION: FeatureCollection = { type: "FeatureCollection", features: [] };

// Real regional shading, not decoration — built from grid_patch's real precomputed neighborhood
// (see pipeline/climate_pipeline/query/lookup.py), not interpolated or fabricated between the
// resolved point and its neighbors. Each real cell becomes one small rectangle polygon sized to
// the grid's own real spacing; a cell with no real data (grid.values[i][j] === null — ocean, or
// land the source dataset itself masks out) is skipped entirely, not filled with a guessed color.
//
// `norm` is 0–1 *within this one patch* (local min/max), not against a fixed global scale — the
// same value would shade differently across two different queries. That's a deliberate choice:
// this map's job is to show real spatial *variation* around the resolved point, which a
// query-spanning fixed scale would wash out for any query where the whole patch sits far from
// that scale's assumed range (e.g. a mild query would render as a flat, uninformative color under
// a scale calibrated for extreme cases).
function buildGridGeoJson(grid: GridPatch): FeatureCollection {
  const realValues = grid.values.flat().filter((v): v is number => v !== null);
  if (realValues.length === 0) return EMPTY_FEATURE_COLLECTION;

  const min = Math.min(...realValues);
  const max = Math.max(...realValues);
  const span = max - min || 1; // every real cell identical (or only one) — avoid a divide-by-zero, not a real edge case to over-think

  // Real ISIMIP resolution is 0.5°; falls back to that when a patch is too narrow (1 distinct
  // lon or lat, e.g. a small radius_deg or a fixture in a test) to measure its own spacing.
  const lonStep = grid.lons.length > 1 ? Math.abs(grid.lons[1] - grid.lons[0]) : 0.5;
  const latStep = grid.lats.length > 1 ? Math.abs(grid.lats[1] - grid.lats[0]) : 0.5;
  const halfLon = lonStep / 2;
  const halfLat = latStep / 2;

  const features: Feature[] = [];
  grid.lats.forEach((lat, i) => {
    grid.lons.forEach((lon, j) => {
      const value = grid.values[i]?.[j];
      if (value === null || value === undefined) return;
      features.push({
        type: "Feature",
        properties: { value, norm: (value - min) / span },
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [lon - halfLon, lat - halfLat],
              [lon + halfLon, lat - halfLat],
              [lon + halfLon, lat + halfLat],
              [lon - halfLon, lat + halfLat],
              [lon - halfLon, lat - halfLat],
            ],
          ],
        },
      });
    });
  });
  return { type: "FeatureCollection", features };
}

// MapLibre v6 no longer auto-detects its own worker script inside a
// bundler's module graph (import.meta.url isn't reliable there) — every
// bundled app must point it at the worker explicitly, once, before the
// first map is constructed. Without this, maps construct without error but
// never fire "load": the worker never starts, so source data (our
// GeoJSON country polygons) never finishes processing.
setWorkerUrl(maplibreWorkerUrl);

// Self-hosted — no tile server, no third party, no API key. The app only
// ever needs to show where a region is, not streets or terrain, so this is
// one static GeoJSON file (public/world-countries.geojson, Natural Earth
// 1:110m, public domain) served from the same CloudFront distribution as
// everything else, styled directly as fill + line layers. Two earlier
// attempts were rejected: MapLibre's own "demotiles" demo is too sparse to
// show anything at a regional zoom, and a real vector-tile basemap
// (OpenFreeMap) is a free third-party service with no scaling guarantee —
// see repo README "Status" table on indicator/precompute decisions this
// will eventually connect to.
const BASE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    countries: {
      type: "geojson",
      data: "/world-countries.geojson",
    },
  },
  layers: [
    {
      id: "ocean",
      type: "background",
      paint: { "background-color": "#cfe8f3" },
    },
    {
      id: "land",
      type: "fill",
      source: "countries",
      paint: { "fill-color": "#e8e4d8" },
    },
    {
      id: "land-border",
      type: "line",
      source: "countries",
      paint: { "line-color": "#b9b39f", "line-width": 1 },
    },
  ],
};

interface ResultMapProps {
  title: string;
  center: MapCenter;
  zoom: number;
  /** 0 (least severe) to 1 (most severe), used only for the marker color. */
  intensity: number;
  valueLabel: string;
  /** Real precomputed neighboring cells around `center` — renders as region shading, not just
   * the single dot. Optional so a caller with no grid data yet (or none at all) still renders a
   * valid map, same as before this existed. */
  grid?: GridPatch;
  /** Rendered between the header and the map canvas, e.g. an indicator toggle. */
  toggle?: ReactNode;
}

function markerColor(intensity: number): string {
  const clamped = Math.max(0, Math.min(1, intensity));
  // Amber to red: consistent with "more severe" reading as "more saturated red."
  const hue = 40 - clamped * 40;
  return `hsl(${hue}, 85%, 45%)`;
}

export function ResultMap({ title, center, zoom, intensity, valueLabel, grid, toggle }: ResultMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markerRef = useRef<Marker | null>(null);
  // MapLibre only allows addSource/addLayer once the map's "load" event has actually fired —
  // calling them from the grid-update effect below (which can run before that, e.g. on the very
  // first render) would throw. This ref is the real signal for "safe to touch the grid source
  // now," set once by the mount effect's own "load" handler.
  const isMapLoadedRef = useRef(false);
  // Kept current on every render (not just via the grid-effect below) so the "load" handler —
  // which fires asynchronously and can land after several renders have already happened — always
  // has the real, latest grid to apply on its one-shot initial setData, not whatever `grid` was
  // at the moment the map was first constructed.
  const latestGridRef = useRef(grid);
  latestGridRef.current = grid;

  useEffect(() => {
    if (!containerRef.current) return;

    const map = new MapLibreMap({
      container: containerRef.current,
      style: BASE_STYLE,
      center: [center.lon, center.lat],
      zoom,
      attributionControl: { compact: true },
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.once("load", () => {
      map.addSource(GRID_SOURCE_ID, {
        type: "geojson",
        data: latestGridRef.current ? buildGridGeoJson(latestGridRef.current) : EMPTY_FEATURE_COLLECTION,
      });
      map.addLayer({
        id: GRID_LAYER_ID,
        type: "fill",
        source: GRID_SOURCE_ID,
        paint: { "fill-color": GRID_FILL_COLOR, "fill-opacity": 0.55 },
      });
      isMapLoadedRef.current = true;
    });
    mapRef.current = map;

    return () => {
      isMapLoadedRef.current = false;
      map.remove();
      mapRef.current = null;
    };
    // Intentionally mount-only: center/zoom changes are handled by the
    // flyTo effect below, so the map isn't torn down and rebuilt on every
    // query. (The lingering exhaustive-deps warning here is expected.)
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    map.flyTo({ center: [center.lon, center.lat], zoom, duration: 800 });

    markerRef.current?.remove();
    const el = document.createElement("div");
    el.className = "result-map-marker";
    el.style.backgroundColor = markerColor(intensity);
    markerRef.current = new Marker({ element: el })
      .setLngLat([center.lon, center.lat])
      .addTo(map);
  }, [center.lon, center.lat, zoom, intensity]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapLoadedRef.current) return;
    const source = map.getSource(GRID_SOURCE_ID) as GeoJSONSource | undefined;
    source?.setData(grid ? buildGridGeoJson(grid) : EMPTY_FEATURE_COLLECTION);
  }, [grid]);

  return (
    <div className="result-map">
      <div ref={containerRef} className="result-map-canvas" />
      <div className="result-map-header">
        <h3>{title}</h3>
        <span className="result-map-value">{valueLabel}</span>
      </div>
      {toggle}
    </div>
  );
}
