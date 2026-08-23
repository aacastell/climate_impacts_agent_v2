import type { QueryAnswer } from "../api/types";
import "./NarrationPanel.css";

interface NarrationPanelProps {
  answer: QueryAnswer;
}

export function NarrationPanel({ answer }: NarrationPanelProps) {
  return (
    <div className="narration-panel">
      <p className="narration-text">{answer.narration}</p>
      <ul className="narration-disclaimers">
        {answer.disclaimers.map((disclaimer) => (
          <li key={disclaimer}>{disclaimer}</li>
        ))}
      </ul>
    </div>
  );
}
