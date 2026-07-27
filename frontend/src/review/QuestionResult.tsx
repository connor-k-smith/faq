import { useMutation } from "@tanstack/react-query";
import { apiRequest as request } from "../apiClient";
import { MutationError } from "../MutationError";
import { AdvisoryResponseForm } from "./AdvisoryResponseForm";
import { DecisionForm } from "./DecisionForm";
import { closePolicyCopy } from "./formatters";
import { OutcomeEffectForm } from "./OutcomeEffectForm";
import { ResolutionSummary } from "./ResolutionSummary";
import { ResponseView } from "./ResponseView";
import type { Question } from "./types";
export function QuestionResult({
  askId,
  question,
  canDecide,
  canCreateSuccessor,
}: {
  askId: string;
  question: Question;
  canDecide: boolean;
  canCreateSuccessor: boolean;
}) {
  const decision = question.decision,
    names = question.assignments
      .filter((a) => a.origin !== "unsolicited")
      .map((a) => a.display_name);
  const successor = useMutation({
    mutationFn: () =>
      request<{ id: string }>(
        `/api/asks/${askId}/questions/${question.id}/successor`,
        "POST",
      ),
    onSuccess: (created) => window.location.assign(`/a/${created.id}/edit`),
  });
  return (
    <article className="result-question" id={`question-${question.id}`}>
      <header>
        <span>Q{question.ordinal + 1}</span>
        <div>
          <p>
            {question.primitive.replace("_", " ")} · v{question.version}
            {question.overdue ? " · overdue" : ""}
          </p>
          <h2>{question.prompt}</h2>
          <strong className="primarily-for">
            Primarily for: {names.join(", ") || "No assigned stakeholders"}.
          </strong>
          <small>{closePolicyCopy(question.close_policy)}</small>
          {question.supersedes_question_id && (
            <small>
              Corrected after an earlier response; current evidence starts with
              this version.
            </small>
          )}
          {question.copied_from_question_id && (
            <small>Delegated copy; activation dependencies were cleared.</small>
          )}
        </div>
      </header>
      <div className="response-grid">
        {question.assignments.map((a) => (
          <ResponseView key={a.id} question={question} assignment={a} />
        ))}
      </div>
      {decision?.advisory_disagreement && (
        <p className="advisory-warning" role="status">
          <strong>Advisory disagreement</strong> · Member input differs from the
          determining outcome. This is not a conflict and does not change the
          Decision.
        </p>
      )}
      {question.can_contribute_advisory && (
        <AdvisoryResponseForm askId={askId} question={question} />
      )}
      {!decision && question.state === "open" && (
        <p className="collection-state">
          <strong>Collecting responses · open</strong>
          {canDecide ? " · owner judgment remains available" : ""}
        </p>
      )}
      {decision?.resolution && <ResolutionSummary decision={decision} />}
      {decision && (decision.historical || decision.state === "superseded") && (
        <div className="committed-decision">
          <p className="eyebrow">Historical Decision · superseded</p>
          <p>This Decision remains readable but is no longer current.</p>
          <blockquote>{decision.statement}</blockquote>
          {decision.successor_decision_id && (
            <a
              className="text-button"
              href={`/d/${decision.successor_decision_id}.md`}
            >
              Export current Decision
            </a>
          )}
        </div>
      )}
      {decision?.state === "committed" && question.outcome_effect ? (
        <div className="committed-decision">
          <p className="eyebrow">Canonical Decision · complete</p>
          <blockquote>{decision.statement}</blockquote>
          {decision.substantive_evidence_count === 0 && (
            <p className="judgment-note">
              Owner judgment without a substantive stakeholder response.
            </p>
          )}
          <small>
            {question.outcome_effect}
            {question.outcome_effect_note
              ? `: ${question.outcome_effect_note}`
              : ""}
            {decision.shared_with_recipients_at
              ? " · shared with recipients"
              : ""}
          </small>
        </div>
      ) : decision?.state === "committed" ? (
        <OutcomeEffectForm askId={askId} question={question} />
      ) : canDecide ? (
        <DecisionForm askId={askId} question={question} />
      ) : null}
      {decision?.supersedes_decision_id && (
        <p className="lineage-notice">
          Current correction Decision.{" "}
          <a href={`/d/${decision.supersedes_decision_id}.md`}>
            Export superseded Decision
          </a>
        </p>
      )}
      {canCreateSuccessor &&
        question.state === "closed" &&
        decision?.state === "committed" &&
        !decision.successor_decision_id && (
          <div className="review-actions">
            <button
              className="text-button"
              type="button"
              disabled={successor.isPending}
              onClick={() => successor.mutate()}
            >
              {successor.isPending
                ? "Creating correction..."
                : "Create correction successor"}
            </button>
            <MutationError mutation={successor} />
          </div>
        )}
    </article>
  );
}
