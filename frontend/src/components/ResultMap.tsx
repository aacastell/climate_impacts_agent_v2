import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { Map as MapLibreMap, Marker, NavigationControl, setWorkerUrl } from "maplibre-gl";
import type { GeoJSONSource } from "maplibre-gl";
import type { Feature, FeatureCollection } from "geojson";
import "maplibre-gl/dist/maplibre-gl.css";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import type { StyleSpecification } from "@maplibre/maplibre-gl-style-spec";
import type { MapCenter, GridPatch } from "../api/types";
import type { ColorScale } from "../colorScales";
import { colorAt, cssGradient, mapLibreFillExpression } from "../colorScales";
import "./ResultMap.css";

const GRID_SOURCE_ID = "indicator-grid";
const GRID_LAYER_ID = "indicator-grid-fill";

const EMPTY_FEATURE_COLLECTION: FeatureCollection = { type: "FeatureCollection", features: [] };

// Real regional shading, not decoration — built from grid_patch's real precomputed neighborhood
// (see pipeline/climate_pipeline/query/lookup.py), not interpolated or fabricated between the
// resolved point and its neighbors. Each real cell becomes one small rectangle polygon sized to
// the grid's own real spacing; a cell with no real data (grid.values[i][j] === null — ocean, or
// land the source dataset itself masks out) is skipped entirely, not filled with a guessed color.
//
// Only the real value is carried as a feature property — no precomputed normalization here.
// Color comes from the caller's own ColorScale (colorScales.ts), applied via a MapLibre paint
// expression (see the grid-paint effect below), so this function has one job: real geometry.
function buildGridGeoJson(grid: GridPatch): FeatureCollection {
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
        properties: { value },
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

// Compact, human-readable — full float precision would clutter a legend that only needs to
// orient the reader to roughly what a color means, not report an exact figure (the header's own
// valueLabel already does that for the resolved point).
function formatLegendValue(value: number): string {
  const rounded = Math.abs(value) >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded >= 0 && value !== 0 ? "+" : ""}${rounded}`;
}

function Legend({ scale, unit }: { scale: ColorScale; unit: string }) {
  const min = scale.stops[0].value;
  const max = scale.stops[scale.stops.length - 1].value;
  const mid = scale.stops.length === 3 ? scale.stops[1].value : null;
  return (
    <div className="result-map-legend">
      <div className="result-map-legend-bar" style={{ background: cssGradient(scale) }} />
      <div className="result-map-legend-labels">
        <span>{formatLegendValue(min)}{unit}</span>
        {mid !== null && <span className="result-map-legend-mid">{formatLegendValue(mid)}{unit}</span>}
        <span>{formatLegendValue(max)}{unit}</span>
      </div>
    </div>
  );
}

interface ResultMapProps {
  title: string;
  center: MapCenter;
  zoom: number;
  /** The resolved point's own real value — colors the center marker via `colorScale`, and labels
   * the header alongside `valueLabel`. */
  value: number;
  unit: string;
  valueLabel: string;
  /** Real, per-indicator color language (colorScales.ts) — drives the marker, the grid shading,
   * and the legend, all from the same real domain, so none of the three can disagree. */
  colorScale: ColorScale;
  /** Real precomputed neighboring cells around `center` — renders as region shading, not just
   * the single dot. Optional so a caller with no grid data yet (or none at all) still renders a
   * valid map, same as before this existed. */
  grid?: GridPatch;
  /** Rendered between the header and the map canvas, e.g. an indicator toggle. */
  toggle?: ReactNode;
}

export function ResultMap({ title, center, zoom, value, unit, valueLabel, colorScale, grid, toggle }: ResultMapProps) {
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
  // has the real, latest grid/scale to apply on its one-shot initial setup, not whatever they
  // were at the moment the map was first constructed.
  const latestGridRef = useRef(grid);
  latestGridRef.current = grid;
  const latestColorScaleRef = useRef(colorScale);
  latestColorScaleRef.current = colorScale;

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
        paint: {
          "fill-color": mapLibreFillExpression(latestColorScaleRef.current),
          "fill-opacity": 0.55,
        },
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
    el.style.backgroundColor = colorAt(colorScale, value);
    markerRef.current = new Marker({ element: el })
      .setLngLat([center.lon, center.lat])
      .addTo(map);
  }, [center.lon, center.lat, zoom, value, colorScale]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapLoadedRef.current) return;
    const source = map.getSource(GRID_SOURCE_ID) as GeoJSONSource | undefined;
    source?.setData(grid ? buildGridGeoJson(grid) : EMPTY_FEATURE_COLLECTION);
    // A different indicator (different colorScale) needs the grid layer's own paint expression
    // updated too, not just the source data — the previous indicator's domain/palette would
    // otherwise silently keep coloring the new one's cells.
    map.setPaintProperty(GRID_LAYER_ID, "fill-color", mapLibreFillExpression(colorScale));
  }, [grid, colorScale]);

  return (
    <div className="result-map">
      <div ref={containerRef} className="result-map-canvas" />
      <div className="result-map-header">
        <h3>{title}</h3>
        <span className="result-map-value">{valueLabel}</span>
      </div>
      <Legend scale={colorScale} unit={unit} />
      {toggle}
    </div>
  );
}
