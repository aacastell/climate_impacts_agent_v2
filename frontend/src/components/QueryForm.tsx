import { useState } from "react";
import type { FormEvent } from "react";
import "./QueryForm.css";

interface QueryFormProps {
  onSubmit: (question: string) => void;
  isLoading: boolean;
}

const EXAMPLES = [
  "How will maize yields in Iowa change at 2°C of warming?",
  "What happens to rice around the Mekong Delta at 3°C?",
  "Spring wheat in Punjab at 1.5°C global warming",
];

export function QueryForm({ onSubmit, isLoading }: QueryFormProps) {
  const [question, setQuestion] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || isLoading) return;
    onSubmit(question.trim());
  }

  return (
    <form className="query-form" onSubmit={handleSubmit}>
      <label htmlFor="question" className="query-form-label">
        Ask about a region, a crop, and a warming level
      </label>
      <div className="query-form-row">
        <input
          id="question"
          type="text"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={EXAMPLES[0]}
          disabled={isLoading}
          autoComplete="off"
        />
        <button type="submit" disabled={isLoading || !question.trim()}>
          {isLoading ? "Asking…" : "Ask"}
        </button>
      </div>
      <div className="query-form-examples">
        Try:{" "}
        {EXAMPLES.map((example, i) => (
          <span key={example}>
            <button
              type="button"
              className="query-form-example"
              onClick={() => setQuestion(example)}
              disabled={isLoading}
            >
              {example}
            </button>
            {i < EXAMPLES.length - 1 ? " · " : ""}
          </span>
        ))}
      </div>
    </form>
  );
}
