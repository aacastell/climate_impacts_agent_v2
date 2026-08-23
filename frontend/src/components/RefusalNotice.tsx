import type { QueryRefusal } from "../api/types";
import "./RefusalNotice.css";

interface RefusalNoticeProps {
  refusal: QueryRefusal;
}

// A typed, deterministic refusal — not an error. See repo README
// "Conventions": a high refusal rate is an accepted design property.
export function RefusalNotice({ refusal }: RefusalNoticeProps) {
  return (
    <div className="refusal-notice" role="status">
      <span className="refusal-notice-reason">{refusal.reason.replaceAll("_", " ")}</span>
      <p>{refusal.message}</p>
    </div>
  );
}
