import { useEffect, useRef } from "react";
import { Map as MapLibreMap, Marker, NavigationControl, setWorkerUrl } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import type { StyleSpecification } from "@maplibre/maplibre-gl-style-spec";
import type { MapCenter } from "../api/types";
import "./ResultMap.css";

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
}

function markerColor(intensity: number): string {
  const clamped = Math.max(0, Math.min(1, intensity));
  // Amber to red: consistent with "more severe" reading as "more saturated red."
  const hue = 40 - clamped * 40;
  return `hsl(${hue}, 85%, 45%)`;
}

export function ResultMap({ title, center, zoom, intensity, valueLabel }: ResultMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markerRef = useRef<Marker | null>(null);

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
    mapRef.current = map;

    return () => {
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

  return (
    <div className="result-map">
      <div className="result-map-header">
        <h3>{title}</h3>
        <span className="result-map-value">{valueLabel}</span>
      </div>
      <div ref={containerRef} className="result-map-canvas" />
    </div>
  );
}
