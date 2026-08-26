import { useState } from "react";
import { apiClient } from "./api";
import type { ClimateIndicatorId, GridPatch, NarrationResult, QueryAnswer, QueryClarify, QueryResponse } from "./api/types";
import { QueryForm } from "./components/QueryForm";
import { ResultMap } from "./components/ResultMap";
import { IndicatorToggle } from "./components/IndicatorToggle";
import { NarrationPanel } from "./components/NarrationPanel";
import { ClarifyPrompt } from "./components/ClarifyPrompt";
import { RefusalNotice } from "./components/RefusalNotice";
import { ProvenanceFooter } from "./components/ProvenanceFooter";
import { colorScaleForIndicator, colorScaleForYield, gridDomain, gridMaxAbs } from "./colorScales";
import { applyCropMask, fetchPrecomputedField } from "./precomputedFetch";
import type { PrecomputedField } from "./precomputedFetch";
import "./App.css";

// Fallback domains for callers with no real grid yet (still loading, or MockApiClient
// — see types.ts's own comment on the two real response shapes) — real
// magnitude estimates, same basis as the scale table this replaced, used only so the marker
// still gets a sensible color before a real spatial patch exists to derive one from.
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

interface HasFieldOrOutputField {
  value?: number;
  grid?: GridPatch;
  outputField?: string;
}

// Either shape is real (see types.ts): already-inline value/grid (MockApiClient), or
// a real outputField identifier this component fetched and cached itself (the real backend's
// ADR-004-restored path). null means genuinely still loading, not an error — the caller renders
// that as a real loading state, not a fabricated placeholder value.
function resolvedField(payload: HasFieldOrOutputField, fetched: Record<string, PrecomputedField>): PrecomputedField | null {
  if (payload.value !== undefined) {
    return { value: payload.value, grid: payload.grid ?? { lons: [], lats: [], values: [] } };
  }
  if (payload.outputField && fetched[payload.outputField]) {
    return fetched[payload.outputField];
  }
  return null;
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

  // Real client-side fetches (ADR-004's restored decision — see frontend/src/precomputedFetch.ts)
  // keyed by outputField, so climate fields and the crop's own yield field share one cache. Each
  // entry lands independently as its own fetch resolves — real, genuinely staggered map loading,
  // not a fabricated reveal animation.
  const [fetchedFields, setFetchedFields] = useState<Record<string, PrecomputedField>>({});

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

  async function loadPrecomputedFields(answer: QueryAnswer) {
    const { lon, lat } = answer.climateMap.center;
    const year = answer.interpretation.year;

    // The crop's own yield field, fetched once — every climate indicator's real crop mask
    // depends on it (see precomputedFetch.applyCropMask), so it starts alongside them, not after.
    const yieldOutputField = answer.sectorMap.outputField;
    const yieldPromise = yieldOutputField
      ? fetchPrecomputedField(yieldOutputField, year, lon, lat).then((field) => {
          setFetchedFields((prev) => ({ ...prev, [yieldOutputField]: field }));
          return field;
        })
      : null;

    for (const indicator of answer.climateMap.indicators) {
      const outputField = indicator.outputField;
      if (!outputField) continue; // inline value/grid already provided — MockApiClient
      fetchPrecomputedField(outputField, year, lon, lat)
        .then(async (field) => {
          // Render unmasked the moment this field's own fetch resolves (real progressive
          // loading), then re-render masked once the yield field also resolves, whichever order
          // they actually finish in.
          setFetchedFields((prev) => ({ ...prev, [outputField]: field }));
          const yieldField = yieldPromise ? await yieldPromise : null;
          if (yieldField) {
            setFetchedFields((prev) => ({ ...prev, [outputField]: applyCropMask(field, yieldField) }));
          }
        })
        .catch(() => {
          // A real, isolated failure fetching one field shouldn't break the other maps — this
          // one just stays in its loading state rather than crashing the page.
        });
    }
  }

  function handleResponse(result: QueryResponse) {
    setResponse(result);
    setFetchedFields({});
    if (result.kind === "answer") {
      void loadNarration(result);
      void loadPrecomputedFields(result);
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

  const selectedField = selectedIndicator ? resolvedField(selectedIndicator, fetchedFields) : null;
  const yieldField = answer ? resolvedField(answer.sectorMap, fetchedFields) : null;

  const climateColorScale = selectedIndicator
    ? colorScaleForIndicator(
        selectedIndicator.id,
        (selectedField && gridDomain(selectedField.grid)) || FALLBACK_DOMAIN[selectedIndicator.id],
      )
    : null;
  const yieldColorScale = colorScaleForYield(yieldField ? gridMaxAbs(yieldField.grid) : FALLBACK_YIELD_MAX_ABS);

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

      {answer && selectedIndicator && climateColorScale && (
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
              value={selectedField?.value ?? 0}
              unit={selectedIndicator.unit}
              colorScale={climateColorScale}
              valueLabel={selectedField ? formatSigned(selectedField.value, selectedIndicator.unit) : "Loading…"}
              grid={selectedField?.grid}
              isLoading={!selectedField}
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
              value={yieldField?.value ?? 0}
              unit={answer.sectorMap.unit}
              colorScale={yieldColorScale}
              valueLabel={yieldField ? formatSigned(yieldField.value, answer.sectorMap.unit) : "Loading…"}
              grid={yieldField?.grid}
              isLoading={!yieldField}
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
