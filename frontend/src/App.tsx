import { useState } from "react";
import { apiClient } from "./api";
import type { QueryResponse } from "./api/types";
import { QueryForm } from "./components/QueryForm";
import { ResultMap } from "./components/ResultMap";
import { NarrationPanel } from "./components/NarrationPanel";
import { RefusalNotice } from "./components/RefusalNotice";
import { ProvenanceFooter } from "./components/ProvenanceFooter";
import "./App.css";

// Yield changes rarely exceed ±40% at the warming levels this system
// covers; used only to scale the sector map marker color, not displayed.
const SECTOR_INTENSITY_SCALE = 40;
const CLIMATE_INTENSITY_SCALE = 5;

function App() {
  const [response, setResponse] = useState<QueryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

      {response?.kind === "answer" && (
        <div className="app-results">
          <div className="app-interpretation">
            Showing <strong>{response.interpretation.crop.replaceAll("_", " ")}</strong> in{" "}
            <strong>{response.interpretation.region}</strong> at{" "}
            <strong>{response.interpretation.warmingLevelC}°C</strong> global warming.
          </div>

          <div className="app-maps">
            <ResultMap
              title={response.climateMap.title}
              center={response.climateMap.center}
              zoom={response.climateMap.zoom}
              intensity={response.climateMap.value / CLIMATE_INTENSITY_SCALE}
              valueLabel={`+${response.climateMap.value}${response.climateMap.unit}`}
            />
            <ResultMap
              title={response.sectorMap.title}
              center={response.sectorMap.center}
              zoom={response.sectorMap.zoom}
              intensity={
                0.5 - response.sectorMap.range[0] / SECTOR_INTENSITY_SCALE / 2
              }
              valueLabel={`${response.sectorMap.range[0]} to ${response.sectorMap.range[1]}${response.sectorMap.unit}`}
            />
          </div>

          <NarrationPanel answer={response} />
          <ProvenanceFooter provenance={response.provenance} />
        </div>
      )}
    </div>
  );
}

export default App;
