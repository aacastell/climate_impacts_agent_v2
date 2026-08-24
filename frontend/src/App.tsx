import { useState } from "react";
import { apiClient } from "./api";
import type { ClimateIndicatorId, ClimateIndicatorPayload, QueryResponse } from "./api/types";
import { QueryForm } from "./components/QueryForm";
import { ResultMap } from "./components/ResultMap";
import { IndicatorToggle } from "./components/IndicatorToggle";
import { NarrationPanel } from "./components/NarrationPanel";
import { RefusalNotice } from "./components/RefusalNotice";
import { ProvenanceFooter } from "./components/ProvenanceFooter";
import "./App.css";

// Yield changes rarely exceed ±40% at the warming levels this system
// covers; used only to scale the sector map marker color, not displayed.
const SECTOR_INTENSITY_SCALE = 40;

// Per-indicator scale used only to map a value onto the 0–1 marker-color
// range — each indicator has a different plausible magnitude, so one shared
// scale (as when there was only one climate indicator) no longer works.
// useAbs: severity reads as "how far from zero," not "which direction" —
// true for indicators where either direction can be the concerning one.
const INDICATOR_INTENSITY: Record<ClimateIndicatorId, { scale: number; useAbs?: boolean }> = {
  temp_change: { scale: 5 },
  precip_change: { scale: 25, useAbs: true },
  consecutive_dry_days: { scale: 25 },
  extreme_heat_days: { scale: 40 },
};

function indicatorIntensity(indicator: ClimateIndicatorPayload): number {
  const { scale, useAbs } = INDICATOR_INTENSITY[indicator.id];
  const magnitude = useAbs ? Math.abs(indicator.value) : indicator.value;
  return magnitude / scale;
}

function formatSigned(value: number, unit: string): string {
  return `${value >= 0 ? "+" : ""}${value}${unit}`;
}

function App() {
  const [response, setResponse] = useState<QueryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIndicatorId, setSelectedIndicatorId] = useState<ClimateIndicatorId>("temp_change");

  async function handleSubmit(question: string) {
    setIsLoading(true);
    setError(null);
    try {
      const result = await apiClient.submitQuery({ question });
      setResponse(result);
    } catch {
      setError("Something went wrong reaching the server. Try again.");
    } finally {
      setIsLoading(false);
    }
  }

  const answer = response?.kind === "answer" ? response : null;
  const selectedIndicator = answer
    ? (answer.climateMap.indicators.find((indicator) => indicator.id === selectedIndicatorId) ??
      answer.climateMap.indicators[0])
    : null;

  return (
    <div className="app">
      <header className="app-header">
        <h1>ISIMIP Climate Explorer</h1>
        <p>
          Ask how projected climate change affects non-irrigated maize, spring wheat, soy, or
          rice yields, for a region and a global warming level.
        </p>
      </header>

      <QueryForm onSubmit={handleSubmit} isLoading={isLoading} />

      {error && <div className="app-error">{error}</div>}

      {response?.kind === "refusal" && <RefusalNotice refusal={response} />}

      {answer && selectedIndicator && (
        <div className="app-results">
          <div className="app-interpretation">
            Showing <strong>{answer.interpretation.crop.replaceAll("_", " ")}</strong> in{" "}
            <strong>{answer.interpretation.region}</strong> at{" "}
            <strong>{answer.interpretation.warmingLevelC}°C</strong> global warming.
          </div>

          <div className="app-maps">
            <ResultMap
              title={selectedIndicator.title}
              center={answer.climateMap.center}
              zoom={answer.climateMap.zoom}
              intensity={indicatorIntensity(selectedIndicator)}
              valueLabel={formatSigned(selectedIndicator.value, selectedIndicator.unit)}
              toggle={
                <IndicatorToggle
                  indicators={answer.climateMap.indicators}
                  selectedId={selectedIndicator.id}
                  onSelect={setSelectedIndicatorId}
                />
              }
            />
            <ResultMap
              title={answer.sectorMap.title}
              center={answer.sectorMap.center}
              zoom={answer.sectorMap.zoom}
              intensity={Math.abs(answer.sectorMap.value) / SECTOR_INTENSITY_SCALE}
              valueLabel={formatSigned(answer.sectorMap.value, answer.sectorMap.unit)}
            />
          </div>

          <NarrationPanel answer={answer} />
          <ProvenanceFooter provenance={answer.provenance} />
        </div>
      )}
    </div>
  );
}

export default App;
