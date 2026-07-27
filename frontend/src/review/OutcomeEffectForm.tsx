import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiRequest as request } from "../apiClient";
import { MutationError } from "../MutationError";
import type { Question, Results } from "./types";
export function OutcomeEffectForm({
  askId,
  question,
}: {
  askId: string;
  question: Question;
}) {
  const client = useQueryClient(),
    [effect, setEffect] = useState("unchanged"),
    [note, setNote] = useState("");
  const record = useMutation({
    mutationFn: () =>
      request<Results>(
        `/api/asks/${askId}/questions/${question.id}/outcome-effect`,
        "POST",
        { outcome_effect: effect, outcome_effect_note: note || null },
      ),
    onSuccess: (result) => client.setQueryData(["ask-results", askId], result),
  });
  return (
    <form
      className="decision-form outcome-effect-form"
      onSubmit={(e) => {
        e.preventDefault();
        record.mutate();
      }}
    >
      <div>
        <p className="eyebrow">Canonical statement preserved</p>
        <h3>Record the outcome effect to complete</h3>
        <blockquote>{question.decision?.statement}</blockquote>
      </div>
      <label>
        <span>Outcome effect</span>
        <select
          aria-label="Outcome effect"
          value={effect}
          onChange={(e) => setEffect(e.target.value)}
        >
          <option value="unchanged">Unchanged</option>
          <option value="clarified">Clarified</option>
          <option value="changed">Changed</option>
        </select>
      </label>
      {effect !== "unchanged" && (
        <label className="wide">
          <span>Effect note</span>
          <textarea
            aria-label="Effect note"
            required
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
      )}
      <MutationError mutation={record} />
      <button className="primary" disabled={record.isPending}>
        {record.isPending ? "Recording..." : "Record outcome effect"}
      </button>
    </form>
  );
}
