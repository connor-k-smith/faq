import type { Question } from "./types";
export function ResolutionSummary({
  decision,
}: {
  decision: NonNullable<Question["decision"]>;
}) {
  const resolution = decision.resolution!,
    votes = Object.entries(resolution.vote_counts);
  return (
    <section className="resolution-summary" aria-label="Computed resolution">
      <div>
        <p className="eyebrow">
          {decision.state === "proposed"
            ? "Proposed"
            : "Auto-committed · awaiting outcome effect"}
        </p>
        <strong>
          {resolution.computed_winner
            ? `Computed value: ${String(resolution.computed_value)}`
            : "No computed winner"}
        </strong>
      </div>
      <dl>
        <div>
          <dt>Basis</dt>
          <dd>{resolution.computed_basis.replaceAll("_", " ")}</dd>
        </div>
        <div>
          <dt>Responses</dt>
          <dd>
            {resolution.substantive_count} substantive /{" "}
            {resolution.eligible_count} eligible
          </dd>
        </div>
        <div>
          <dt>Quorum</dt>
          <dd>{resolution.quorum_met ? "Met" : "Not met"}</dd>
        </div>
        <div>
          <dt>Conflict</dt>
          <dd>{resolution.conflict ? "Yes" : "No"}</dd>
        </div>
      </dl>
      {votes.length > 0 && (
        <p className="vote-counts">
          Vote counts:{" "}
          {votes.map(([name, count]) => `${name} ${count}`).join(", ")}
        </p>
      )}
      {!resolution.computed_winner && (
        <p className="resolution-guidance">
          {resolution.substantive_count === 0
            ? "No substantive responses were received. Record the owner’s judgment."
            : resolution.conflict
              ? "Responses conflict or are tied. Record the owner’s judgment."
              : "No quorum was reached. Record the owner’s judgment."}
        </p>
      )}
    </section>
  );
}
