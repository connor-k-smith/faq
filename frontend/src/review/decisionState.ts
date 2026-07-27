import type { Question } from "./types";
export type Evidence = Record<string, "determining" | "context">;
export function defaultEvidence(question: Question): Evidence {
  return Object.fromEntries(
    question.assignments
      .filter((a) => a.origin !== "unsolicited")
      .flatMap((a) =>
        a.latest_response
          ? [
              [
                a.latest_response.id,
                a.latest_response.disposition === "answered"
                  ? "determining"
                  : "context",
              ],
            ]
          : [],
      ),
  ) as Evidence;
}
export function decisionServerIdentity(question: Question) {
  return JSON.stringify({
    questionVersion: question.version,
    proposalId:
      question.decision?.state === "proposed" ? question.decision.id : null,
    proposalValue:
      question.decision?.state === "proposed"
        ? question.decision.resolution?.computed_value
        : null,
    evidence: question.assignments.map((a) => [
      a.id,
      a.latest_response?.id ?? null,
      a.latest_response?.version ?? null,
    ]),
  });
}
export function structuredValue(
  question: Question,
  value: string,
  many: string[],
) {
  return question.primitive === "select_many"
    ? many
    : question.primitive === "number"
      ? Number(value)
      : value;
}
