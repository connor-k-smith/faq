import type { Dependency, DependencyOperator, Question } from "./types";
export function QuestionDependencyEditor({
  questions,
  questionId,
  value,
  onChange,
}: {
  questions: Question[];
  questionId?: string;
  value: Dependency | null;
  onChange: (value: Dependency | null) => void;
}) {
  const prerequisite = questions.find(
    (question) => question.id === value?.question_id,
  );
  const multiple = value?.op === "in" || value?.op === "not_in";
  const setOperator = (op: DependencyOperator) =>
    onChange(
      value
        ? {
            question_id: value.question_id,
            op,
            ...(!["answered", "unanswered"].includes(op)
              ? { value: ["in", "not_in"].includes(op) ? [] : "" }
              : {}),
          }
        : null,
    );
  return (
    <fieldset className="dependency-editor wide">
      <legend>Activation dependency</legend>
      <label>
        <span>Prerequisite Question</span>
        <select
          aria-label="Prerequisite Question"
          value={value?.question_id ?? ""}
          onChange={(e) =>
            onChange(
              e.target.value
                ? { question_id: e.target.value, op: "answered" }
                : null,
            )
          }
        >
          <option value="">Always active</option>
          {questions
            .filter((q) => q.id !== questionId)
            .map((q) => (
              <option key={q.id} value={q.id}>
                Question {q.ordinal + 1}: {q.prompt}
              </option>
            ))}
        </select>
      </label>
      {value && (
        <label>
          <span>Condition</span>
          <select
            aria-label="Dependency condition"
            value={value.op}
            onChange={(e) => setOperator(e.target.value as DependencyOperator)}
          >
            <option value="answered">is answered</option>
            <option value="unanswered">is unanswered</option>
            <option value="eq">equals</option>
            <option value="neq">does not equal</option>
            <option value="in">includes any of</option>
            <option value="not_in">includes none of</option>
          </select>
        </label>
      )}
      {value &&
        !["answered", "unanswered"].includes(value.op) &&
        prerequisite && (
          <DependencyValue
            question={prerequisite}
            multiple={multiple}
            value={value.value}
            onChange={(next) => onChange({ ...value, value: next })}
          />
        )}
      <small>Activation changes after you save the Question.</small>
    </fieldset>
  );
}
function DependencyValue({
  question,
  multiple,
  value,
  onChange,
}: {
  question: Question;
  multiple: boolean;
  value?: string | string[];
  onChange: (v: string | string[]) => void;
}) {
  if (question.options.length)
    return (
      <label>
        <span>Value</span>
        <select
          aria-label="Dependency value"
          multiple={multiple}
          value={
            multiple
              ? Array.isArray(value)
                ? value
                : []
              : typeof value === "string"
                ? value
                : ""
          }
          onChange={(e) =>
            onChange(
              multiple
                ? Array.from(
                    e.currentTarget.selectedOptions,
                    (option) => option.value,
                  )
                : e.target.value,
            )
          }
        >
          <option value="" disabled={!multiple}>
            Choose a value
          </option>
          {question.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
    );
  return (
    <label>
      <span>Value</span>
      <input
        aria-label="Dependency value"
        value={Array.isArray(value) ? value.join(", ") : (value ?? "")}
        onChange={(e) =>
          onChange(
            multiple
              ? e.target.value
                  .split(",")
                  .map((item) => item.trim())
                  .filter(Boolean)
              : e.target.value,
          )
        }
        placeholder={multiple ? "Comma-separated values" : undefined}
      />
    </label>
  );
}
