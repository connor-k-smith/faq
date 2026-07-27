import { ResponseView } from "./ResponseView";
import type { Results } from "./types";
export function StakeholderResults({ value }: { value: Results }) {
  return (
    <section className="stakeholder-grid" aria-label="Stakeholder results">
      {value.stakeholders.map((stakeholder) => (
        <article className="stakeholder-result" key={stakeholder.recipient_id}>
          <h2>{stakeholder.display_name}</h2>
          {stakeholder.distinct_ip_count > 1 && (
            <p className="ip-warning" role="alert">
              This invitation was used from {stakeholder.distinct_ip_count}{" "}
              distinct IP addresses.
            </p>
          )}
          {stakeholder.questions.map((reference) => {
            const question = value.questions.find(
                (q) => q.id === reference.question_id,
              )!,
              assignment = question.assignments.find(
                (a) => a.id === reference.assignment_id,
              )!;
            return (
              <ResponseView
                key={reference.assignment_id}
                question={question}
                assignment={assignment}
              />
            );
          })}
        </article>
      ))}
      {!value.stakeholders.length && (
        <p className="empty">No stakeholders are assigned to this Ask.</p>
      )}
    </section>
  );
}
