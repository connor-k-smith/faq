import type { Dependency, Question } from "./types";

export function describeDependency(
  dependency: Dependency,
  question?: Question,
) {
  const labels = (
    Array.isArray(dependency.value) ? dependency.value : [dependency.value]
  )
    .filter(Boolean)
    .map(
      (value) =>
        question?.options.find((option) => option.value === value)?.label ??
        value,
    )
    .join(", ");
  return {
    answered: "is answered",
    unanswered: "is unanswered",
    eq: `equals ${labels}`,
    neq: `does not equal ${labels}`,
    in: `includes any of ${labels}`,
    not_in: `includes none of ${labels}`,
  }[dependency.op];
}
