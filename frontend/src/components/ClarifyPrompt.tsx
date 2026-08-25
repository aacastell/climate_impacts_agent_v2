import { useState } from "react";
import type { FormEvent } from "react";
import type { QueryClarify } from "../api/types";
import "./ClarifyPrompt.css";

interface ClarifyPromptProps {
  clarify: QueryClarify;
  isLoading: boolean;
  onAnswer: (answer: string) => void;
}

// The model asked for clarification instead of guessing (see orchestrator.py's SYSTEM_PROMPT) —
// resuming this via queryId is what makes the round-trip a real continuation of the same
// conversation, not a fresh, context-free question.
export function ClarifyPrompt({ clarify, isLoading, onAnswer }: ClarifyPromptProps) {
  const [answer, setAnswer] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!answer.trim() || isLoading) return;
    onAnswer(answer.trim());
  }

  return (
    <form className="clarify-prompt" onSubmit={handleSubmit} role="status">
      <p className="clarify-prompt-question">{clarify.question}</p>
      <div className="clarify-prompt-row">
        <input
          type="text"
          value={answer}
          onChange={(event) => setAnswer(event.target.value)}
          placeholder="Your answer…"
          disabled={isLoading}
          autoComplete="off"
          autoFocus
        />
        <button type="submit" disabled={isLoading || !answer.trim()}>
          {isLoading ? "Sending…" : "Answer"}
        </button>
      </div>
    </form>
  );
}
