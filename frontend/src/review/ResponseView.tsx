import { displayValue, formatElapsed } from "./formatters";
import type { Assignment, Question } from "./types";
export function ResponseView({
  question,
  assignment,
}: {
  question: Question;
  assignment: Assignment;
}) {
  const latest = assignment.latest_response;
  return (
    <section className="response-result">
      <div className="response-head">
        <strong>{assignment.display_name}</strong>
        <span>{formatElapsed(assignment.elapsed_seconds)}</span>
      </div>
      {assignment.origin === "unsolicited" && (
        <p className="response-label">
          <span>Advisory · not asked directly</span>
          {assignment.late && <span>Late</span>}
        </p>
      )}
      {assignment.child_ask_id && (
        <div className="delegation-result">
          <strong>Delegated, non-substantive response</strong>
          <p>
            This response records a handoff and does not determine the parent
            Question. The delegate answers in an independent child Ask.
          </p>
          <a className="text-button" href={`/a/${assignment.child_ask_id}`}>
            Open delegated Ask
          </a>
        </div>
      )}
      {assignment.distinct_ip_count > 1 && (
        <p className="ip-warning">Distinct-IP warning</p>
      )}
      {!assignment.response_visible ? (
        <p className="unanswered">
          Response hidden until visibility conditions are met.
        </p>
      ) : !latest ? (
        <p className="unanswered">Unanswered · {assignment.state}</p>
      ) : (
        <>
          <p className="answer-value">{displayValue(question, latest)}</p>
          {latest.comment && <p className="answer-comment">{latest.comment}</p>}
          {assignment.revisions.length > 1 && (
            <details>
              <summary>{assignment.revisions.length} revisions</summary>
              {assignment.revisions.map((r) => (
                <p key={r.id}>
                  <strong>v{r.version}</strong> {displayValue(question, r)}
                  {r.comment ? ` · ${r.comment}` : ""}
                </p>
              ))}
            </details>
          )}
        </>
      )}
    </section>
  );
}
