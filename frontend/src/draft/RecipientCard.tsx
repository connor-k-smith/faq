import { useMutation } from "@tanstack/react-query";
import { apiRequest as request } from "../apiClient";
import { MutationError } from "../MutationError";
import type { Question, Recipient } from "./types";
export function RecipientCard({
  recipient,
  askId,
  questions,
  readOnly,
  refresh,
}: {
  recipient: Recipient;
  askId: string;
  questions: Question[];
  readOnly: boolean;
  refresh: () => Promise<unknown>;
}) {
  const remove = useMutation({
    mutationFn: () =>
      request<void>(`/api/asks/${askId}/recipients/${recipient.id}`, "DELETE"),
    onSuccess: refresh,
  });
  return (
    <article className="recipient-card">
      <div>
        <strong>{recipient.display_name}</strong>
        <small>{recipient.email ?? "Link delivery"}</small>
        <small className="recipient-workload">
          {recipient.open_assignments} open · {recipient.recent_assignments}{" "}
          assignment{recipient.recent_assignments === 1 ? "" : "s"} across{" "}
          {recipient.recent_asks} Ask{recipient.recent_asks === 1 ? "" : "s"} in
          the last {recipient.window_days} days
        </small>
      </div>
      {!readOnly && (
        <button
          className="icon-button"
          disabled={remove.isPending}
          aria-label={`${remove.isPending ? "Removing" : "Remove"} ${recipient.display_name}`}
          onClick={() =>
            window.confirm(`Remove ${recipient.display_name}?`) &&
            remove.mutate()
          }
        >
          ×
        </button>
      )}
      <details>
        <summary>Recipient preview</summary>
        <p>
          {questions.length
            ? `${questions.length} question${questions.length === 1 ? "" : "s"} assigned on send.`
            : "Add a question to complete this preview."}
        </p>
        {questions.map((q) => (
          <span key={q.id}>{q.prompt}</span>
        ))}
      </details>
      <MutationError mutation={remove} />
    </article>
  );
}
