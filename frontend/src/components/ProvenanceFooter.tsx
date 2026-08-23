import type { Provenance } from "../api/types";
import "./ProvenanceFooter.css";

interface ProvenanceFooterProps {
  provenance: Provenance;
}

// Every published answer carries a provenance record — see repo README
// "Conventions".
export function ProvenanceFooter({ provenance }: ProvenanceFooterProps) {
  return (
    <dl className="provenance-footer">
      <div>
        <dt>Climate model</dt>
        <dd>{provenance.climateModel}</dd>
      </div>
      <div>
        <dt>Crop models</dt>
        <dd>{provenance.cropModels.join(", ")}</dd>
      </div>
      <div>
        <dt>Scenario</dt>
        <dd>{provenance.scenario}</dd>
      </div>
      <div>
        <dt>Run specifier</dt>
        <dd>{provenance.runSpecifier}</dd>
      </div>
      <div>
        <dt>Data version</dt>
        <dd>{provenance.dataVersion}</dd>
      </div>
      <div>
        <dt>Indicator version</dt>
        <dd>{provenance.indicatorVersion}</dd>
      </div>
      <div>
        <dt>Prompt version</dt>
        <dd>{provenance.promptVersion}</dd>
      </div>
    </dl>
  );
}
