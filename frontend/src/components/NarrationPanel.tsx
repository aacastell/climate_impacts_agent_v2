import type { NarrationResult } from "../api/types";
import "./NarrationPanel.css";

interface NarrationPanelProps {
  narration: NarrationResult | null;
  isLoading: boolean;
  error: string | null;
  disclaimers: string[];
}

export function NarrationPanel({ narration, isLoading, error, disclaimers }: NarrationPanelProps) {
  return (
    <div className="narration-panel">
      {isLoading && <p className="narration-loading">Generating an explanation…</p>}
      {!isLoading && error && <p className="narration-error">{error}</p>}
      {!isLoading && narration && (
        <>
          <p className="narration-text">{narration.narration}</p>
          {narration.status === "SCIENTIFIC_DISAGREEMENT" && (
            // A real, distinct state (ADR-007 Step 4) — the literature-grounded explanation and
            // the crop model's own projection disagree, after real retries. Not an error: a
            // genuine finding worth surfacing plainly, not silently smoothed over.
            <p className="narration-disagreement" role="status">
              Note: this explanation, grounded in climate evidence and literature, doesn't fully
              reconcile with the crop model's own projection above — both are shown as computed,
              not adjusted to agree.
            </p>
          )}
        </>
      )}
      <ul className="narration-disclaimers">
        {disclaimers.map((disclaimer) => (
          <li key={disclaimer}>{disclaimer}</li>
        ))}
      </ul>
    </div>
  );
}
