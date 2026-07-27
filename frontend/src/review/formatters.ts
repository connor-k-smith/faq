import type { Question, Revision } from "./types";
export function formatElapsed(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}
export function closePolicyCopy(policy: Question["close_policy"]) {
  if (policy === "all_responded")
    return "Closes after every assigned stakeholder responds.";
  if (policy === "deadline")
    return "Closes at the Ask deadline; owner judgment remains available.";
  return "Closes when everyone responds or at the deadline, whichever comes first.";
}
export function displayValue(question: Question, response: Revision) {
  if (response.disposition !== "answered")
    return response.disposition.replace("_", " ");
  if (question.primitive === "select_many" && Array.isArray(response.value))
    return response.value
      .map(
        (value) =>
          question.options.find((item) => item.value === value)?.label ??
          String(value),
      )
      .join(", ");
  if (question.primitive === "date" && typeof response.value === "string") {
    const [y, m, d] = response.value.split("-").map(Number);
    if (y && m && d)
      return new Intl.DateTimeFormat(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      }).format(new Date(y, m - 1, d));
  }
  return (
    question.options.find((item) => item.value === response.value)?.label ??
    String(response.value ?? "")
  );
}
