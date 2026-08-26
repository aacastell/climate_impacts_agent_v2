import { useState } from "react";
import { apiClient } from "./api";
import type { ClimateIndicatorId, NarrationResult, QueryAnswer, QueryClarify, QueryResponse } from "./api/types";
import { QueryForm } from "./components/QueryForm";
import { ResultMap } from "./components/ResultMap";
import { IndicatorToggle } from "./components/IndicatorToggle";
import { NarrationPanel } from "./components/NarrationPanel";
import { ClarifyPrompt } from "./components/ClarifyPrompt";
import { RefusalNotice } from "./components/RefusalNotice";
import { ProvenanceFooter } from "./components/ProvenanceFooter";
import { colorScaleForIndicator, colorScaleForYield, gridDomain, gridMaxAbs } from "./colorScales";
import "./App.css";

// Fallback domains for callers with no real grid (MockApiClient, PrecomputedApiClient — see
// types.ts's own comment on why `grid` is optional) — real magnitude estimates, same basis as
// the scale table this replaced, used only so the marker still gets a sensible color without a
// real spatial patch to derive one from.
const FALLBACK_DOMAIN: Record<ClimateIndicatorId, [number, number]> = {
  temp_change: [0, 5],
  precip_change_abs: [-3, 3],
  precip_change_pct: [-25, 25],
  consecutive_dry_days: [0, 25],
  extreme_heat_days: [0, 40],
};
const FALLBACK_YIELD_MAX_ABS = 40;

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

  const climateColorScale = selectedIndicator
    ? colorScaleForIndicator(
        selectedIndicator.id,
        (selectedIndicator.grid && gridDomain(selectedIndicator.grid)) || FALLBACK_DOMAIN[selectedIndicator.id],
      )
    : null;
  const yieldColorScale = answer
    ? colorScaleForYield(answer.sectorMap.grid ? gridMaxAbs(answer.sectorMap.grid) : FALLBACK_YIELD_MAX_ABS)
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

      {answer && selectedIndicator && climateColorScale && yieldColorScale && (
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
              value={selectedIndicator.value}
              unit={selectedIndicator.unit}
              colorScale={climateColorScale}
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
              value={answer.sectorMap.value}
              unit={answer.sectorMap.unit}
              colorScale={yieldColorScale}
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
