import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiRequest as request } from "../apiClient";
import type { AskAggregate } from "../apiTypes";
import { formatElapsed } from "./formatters";
import { QuestionResults } from "./QuestionResults";
import { ReviewStatus } from "./ReviewStatus";
import { StakeholderResults } from "./StakeholderResults";
import type { Results } from "./types";
export function AskReview({ askId }: { askId: string }) {
  const results = useQuery({
    queryKey: ["ask-results", askId],
    queryFn: () => request<Results>(`/api/asks/${askId}/results`),
    refetchInterval: 15_000,
  });
  const ask = useQuery({
    queryKey: ["ask", askId],
    queryFn: () => request<AskAggregate>(`/api/asks/${askId}`),
  });
  const [orientation, setOrientation] = useState<"question" | "stakeholder">(
    "question",
  );
  if (results.isPending)
    return <ReviewStatus text="Opening live results" pending />;
  if (results.isError || !results.data)
    return (
      <ReviewStatus
        text="Results unavailable"
        detail={results.error?.message}
      />
    );
  const value = results.data,
    correction = ask.data?.questions.some((q) => q.supersedes_question_id);
  return (
    <div className="review-shell">
      <header className="author-topbar">
        <a className="wordmark" href="/">
          FAQ
        </a>
        <nav className="review-nav" aria-label="Ask navigation">
          <a href="/">Projects</a>
          <span>/</span>
          <strong>Live results</strong>
        </nav>
        <span className="draft-state">{value.status}</span>
      </header>
      <main className="review-main">
        {value.parent_ask_id && (
          <section
            className="lineage-notice"
            aria-label={correction ? "Correction Ask" : "Delegated Ask"}
          >
            <p className="eyebrow">
              {correction ? "Correction successor" : "Delegated snapshot"}
            </p>
            <h2>
              {correction ? "New Decision cycle" : "Independent follow-up Ask"}
            </h2>
            <p>
              {correction
                ? "This correction has fresh evidence. The prior Ask remains closed as historical record."
                : "This Question was copied for a delegated stakeholder with activation dependencies cleared. Parent responses, comments, and stakeholders are not included in this view."}
            </p>
            <a className="text-button" href={`/a/${value.parent_ask_id}`}>
              Back to parent Ask
            </a>
          </section>
        )}
        <section className="review-heading">
          <div>
            <p className="eyebrow">Review, decide, close</p>
            <h1>{value.title}</h1>
            {value.deadline && (
              <p className={value.overdue ? "overdue" : ""}>
                {value.overdue ? "Overdue since" : "Due"}{" "}
                {new Intl.DateTimeFormat(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                }).format(new Date(value.deadline))}
              </p>
            )}
          </div>
          <div className="review-actions">
            <p>{formatElapsed(value.elapsed_seconds)} elapsed</p>
            {value.status === "sent" && (
              <a className="text-button" href={`/a/${askId}/edit`}>
                Manage invitations
              </a>
            )}
          </div>
        </section>
        <div
          className="orientation"
          role="group"
          aria-label="Results orientation"
        >
          <button
            aria-pressed={orientation === "question"}
            onClick={() => setOrientation("question")}
          >
            Question first
          </button>
          <button
            aria-pressed={orientation === "stakeholder"}
            onClick={() => setOrientation("stakeholder")}
          >
            Stakeholder first
          </button>
        </div>
        {orientation === "question" ? (
          <QuestionResults
            askId={askId}
            value={value}
            canCreateSuccessor={ask.data?.can_create_successor === true}
          />
        ) : (
          <StakeholderResults value={value} />
        )}
      </main>
    </div>
  );
}
