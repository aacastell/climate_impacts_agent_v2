import type { ClimateIndicatorId, ClimateIndicatorPayload } from "../api/types";
import "./IndicatorToggle.css";

const INDICATOR_LABELS: Record<ClimateIndicatorId, string> = {
  temp_change: "Temperature",
  precip_change_abs: "Precipitation (mm)",
  precip_change_pct: "Precipitation (%)",
  consecutive_dry_days: "Dry days",
  extreme_heat_days: "Extreme heat",
};

interface IndicatorToggleProps {
  indicators: ClimateIndicatorPayload[];
  selectedId: ClimateIndicatorId;
  onSelect: (id: ClimateIndicatorId) => void;
}

export function IndicatorToggle({ indicators, selectedId, onSelect }: IndicatorToggleProps) {
  return (
    <div className="indicator-toggle" role="tablist" aria-label="Climate indicator">
      {indicators.map((indicator) => (
        <button
          key={indicator.id}
          type="button"
          role="tab"
          aria-selected={indicator.id === selectedId}
          className={
            indicator.id === selectedId
              ? "indicator-toggle-option indicator-toggle-option-selected"
              : "indicator-toggle-option"
          }
          onClick={() => onSelect(indicator.id)}
        >
          {INDICATOR_LABELS[indicator.id]}
        </button>
      ))}
    </div>
  );
}
