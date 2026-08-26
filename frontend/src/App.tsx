import { useState } from "react";
import { apiClient } from "./api";
import type { ClimateIndicatorId, ClimateIndicatorPayload, NarrationResult, QueryAnswer, QueryClarify, QueryResponse } from "./api/types";
import { QueryForm } from "./components/QueryForm";
import { ResultMap } from "./components/ResultMap";
import { IndicatorToggle } from "./components/IndicatorToggle";
import { NarrationPanel } from "./components/NarrationPanel";
import { ClarifyPrompt } from "./components/ClarifyPrompt";
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
  // mm/day change is typically a small number — 3mm as a plausible-magnitude visualization
  // scale, same rough-estimate basis as every other value in this table, not derived from data.
  precip_change_abs: { scale: 3, useAbs: true },
  precip_change_pct: { scale: 25, useAbs: true },
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

  // Narration is a separate, slower call (RAG + generation + verification, real retries in the
  // real backend) — fetched after the maps are already showing, not blocking them.
  const [narration, setNarration] = useState<NarrationResult | null>(null);
  const [isNarrationLoading, setIsNarrationLoading] = useState(false);
  const [narrationError, setNarrationError] = useState<string | null>(null);

  const [isClarifying, setIsClarifying] = useState(false);

  async function loadNarration(answer: QueryAnswer) {
    setNarration(null);
    setNarrationError(null);
    setIsNarrationLoading(true);
    try {
      const result = await apiClient.fetchNarration(answer.interpretation);
      setNarration(result);
    } catch {
      setNarrationError("Couldn't generate an explanation for this result. The numbers above are still real.");
    } finally {
      setIsNarrationLoading(false);
    }
  }

  function handleResponse(result: QueryResponse) {
    setResponse(result);
    if (result.kind === "answer") {
      void loadNarration(result);
    }
  }

  async function handleSubmit(question: string) {
    setIsLoading(true);
    setError(null);
    setNarration(null);
    setNarrationError(null);
    try {
      const result = await apiClient.submitQuery({ question });
      handleResponse(result);
    } catch {
      setError("Something went wrong reaching the server. Try again.");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleClarifyAnswer(clarify: QueryClarify, answerText: string) {
    setIsClarifying(true);
    setError(null);
    try {
      const result = await apiClient.submitClarifyAnswer({ queryId: clarify.queryId, answer: answerText });
      handleResponse(result);
    } catch {
      setError("Something went wrong reaching the server. Try again.");
    } finally {
      setIsClarifying(false);
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

      {response?.kind === "clarify" && (
        <ClarifyPrompt
          clarify={response}
          isLoading={isClarifying}
          onAnswer={(answerText) => handleClarifyAnswer(response, answerText)}
        />
      )}

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
              grid={selectedIndicator.grid}
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
              grid={answer.sectorMap.grid}
            />
          </div>

          <NarrationPanel
            narration={narration}
            isLoading={isNarrationLoading}
            error={narrationError}
            disclaimers={answer.disclaimers}
          />
          <ProvenanceFooter provenance={answer.provenance} />
        </div>
      )}
    </div>
  );
}

export default App;
