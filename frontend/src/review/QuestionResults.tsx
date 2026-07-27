import { QuestionResult } from "./QuestionResult";
import type { Results } from "./types";
export function QuestionResults({
  askId,
  value,
  canCreateSuccessor,
}: {
  askId: string;
  value: Results;
  canCreateSuccessor: boolean;
}) {
  return (
    <section className="result-stack" aria-label="Question results">
      {value.questions.map((q) => (
        <QuestionResult
          key={q.id}
          askId={askId}
          question={q}
          canDecide={value.can_decide}
          canCreateSuccessor={canCreateSuccessor}
        />
      ))}
      {!value.questions.length && (
        <p className="empty">No Questions have been added to this Ask.</p>
      )}
    </section>
  );
}
