import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { apiRequest as request } from "../apiClient";
import { MutationError } from "../MutationError";
import {
  decisionServerIdentity,
  defaultEvidence,
  structuredValue,
  type Evidence,
} from "./decisionState";
import type { Question, Results } from "./types";

export function DecisionForm({
  askId,
  question,
}: {
  askId: string;
  question: Question;
}) {
  const client = useQueryClient(),
    proposal =
      question.decision?.state === "proposed" ? question.decision : null,
    computed = proposal?.resolution?.computed_value,
    identity = decisionServerIdentity(question);
  const initialValue =
    typeof computed === "string" || typeof computed === "number"
      ? String(computed)
      : (question.options[0]?.value ?? "");
  const [acceptedIdentity, setAcceptedIdentity] = useState(identity),
    [dirty, setDirty] = useState(false),
    [statement, setStatement] = useState(proposal?.statement ?? ""),
    [value, setValue] = useState(initialValue),
    [many, setMany] = useState<string[]>(
      Array.isArray(computed) ? computed.map(String) : [],
    ),
    [effect, setEffect] = useState("unchanged"),
    [note, setNote] = useState(""),
    [share, setShare] = useState(false),
    [evidence, setEvidence] = useState<Evidence>(() =>
      defaultEvidence(question),
    );
  const effectiveStatement = dirty ? statement : (proposal?.statement ?? ""),
    effectiveValue = dirty ? value : initialValue,
    effectiveMany = dirty
      ? many
      : Array.isArray(computed)
        ? computed.map(String)
        : [],
    effectiveEvidence = dirty ? evidence : defaultEvidence(question),
    serverChanged = dirty && identity !== acceptedIdentity;
  const reset = () => {
    setStatement(proposal?.statement ?? "");
    setValue(initialValue);
    setMany(Array.isArray(computed) ? computed.map(String) : []);
    setEffect("unchanged");
    setNote("");
    setShare(false);
    setEvidence(defaultEvidence(question));
    setAcceptedIdentity(identity);
    setDirty(false);
  };
  const commit = useMutation({
    mutationFn: () =>
      request<Results>(
        `/api/asks/${askId}/questions/${question.id}/decision`,
        "POST",
        {
          statement: effectiveStatement,
          value:
            question.primitive === "select_one"
              ? effectiveValue
              : question.primitive === "select_many"
                ? effectiveMany
                : question.primitive === "number"
                  ? Number(effectiveValue)
                  : question.primitive === "date"
                    ? effectiveValue
                    : null,
          evidence: proposal
            ? []
            : Object.entries(effectiveEvidence).map(([response_id, role]) => ({
                response_id,
                role,
              })),
          outcome_effect: effect,
          outcome_effect_note: note || null,
          share_with_recipients: share,
          proposal_id: proposal?.id,
        },
      ),
    onSuccess: async (result) => {
      client.setQueryData(["ask-results", askId], result);
      await client.invalidateQueries({ queryKey: ["ask", askId] });
    },
  });
  const assigned = question.assignments.filter(
    (a) => a.origin !== "unsolicited",
  );
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!serverChanged) commit.mutate();
  }
  return (
    <form
      className="decision-form"
      onSubmit={submit}
      onChange={() => setDirty(true)}
    >
      <div>
        <p className="eyebrow">
          {proposal ? "Proposed resolution" : "Owner judgment"}
        </p>
        <h3>
          {proposal
            ? "Confirm or override the proposal"
            : "Record the canonical outcome"}
        </h3>
        <p>
          {proposal
            ? "Automatic determining evidence is fixed by the server. Confirm the computed value or record an owner override."
            : "Stakeholder responses are evidence, not a vote. You may decide without substantive evidence."}
        </p>
      </div>
      <label className="wide">
        <span>Canonical statement</span>
        <textarea
          aria-label="Canonical statement"
          required
          value={effectiveStatement}
          onChange={(e) => setStatement(e.target.value)}
        />
      </label>
      {question.primitive === "select_one" && (
        <label>
          <span>Structured outcome</span>
          <select
            aria-label="Structured outcome"
            value={effectiveValue}
            onChange={(e) => setValue(e.target.value)}
          >
            {question.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      )}
      {question.primitive === "select_many" && (
        <fieldset className="structured-many">
          <legend>Structured outcome</legend>
          {question.options.map((o) => (
            <label key={o.value}>
              <input
                type="checkbox"
                checked={effectiveMany.includes(o.value)}
                onChange={(e) =>
                  setMany((current) =>
                    e.target.checked
                      ? [...current, o.value]
                      : current.filter((v) => v !== o.value),
                  )
                }
              />{" "}
              {o.label}
            </label>
          ))}
        </fieldset>
      )}
      {(question.primitive === "number" || question.primitive === "date") && (
        <label>
          <span>Structured outcome</span>
          <input
            aria-label="Structured outcome"
            type={question.primitive}
            step={question.primitive === "number" ? "any" : undefined}
            required
            value={effectiveValue}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
      )}
      {!proposal && (
        <fieldset className="evidence">
          <legend>Latest Responses used as evidence</legend>
          {assigned.map(
            (a) =>
              a.latest_response && (
                <label key={a.id}>
                  <input
                    type="checkbox"
                    checked={a.latest_response.id in effectiveEvidence}
                    onChange={(e) =>
                      setEvidence((current) => {
                        const next = { ...current };
                        if (e.target.checked)
                          next[a.latest_response!.id] =
                            a.latest_response!.disposition === "answered"
                              ? "determining"
                              : "context";
                        else delete next[a.latest_response!.id];
                        return next;
                      })
                    }
                  />{" "}
                  {a.display_name}
                  <select
                    aria-label={`Evidence role for ${a.display_name}`}
                    disabled={!(a.latest_response.id in effectiveEvidence)}
                    value={effectiveEvidence[a.latest_response.id] ?? "context"}
                    onChange={(e) =>
                      setEvidence((current) => ({
                        ...current,
                        [a.latest_response!.id]: e.target
                          .value as Evidence[string],
                      }))
                    }
                  >
                    <option
                      value="determining"
                      disabled={a.latest_response.disposition !== "answered"}
                    >
                      Determining
                    </option>
                    <option value="context">Context</option>
                  </select>
                </label>
              ),
          )}
        </fieldset>
      )}
      <label>
        <span>Outcome effect</span>
        <select
          aria-label="Outcome effect"
          value={effect}
          onChange={(e) => setEffect(e.target.value)}
        >
          <option value="unchanged">Unchanged</option>
          <option value="clarified">Clarified</option>
          <option value="changed">Changed</option>
        </select>
      </label>
      {effect !== "unchanged" && (
        <label className="wide">
          <span>What changed or became clearer?</span>
          <textarea
            aria-label="What changed or became clearer?"
            required
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
      )}
      <label className="share-outcome">
        <input
          aria-label="Share this outcome with recipients"
          type="checkbox"
          checked={share}
          onChange={(e) => setShare(e.target.checked)}
        />{" "}
        Share this outcome with recipients
      </label>
      {serverChanged && (
        <div className="server-change-conflict" role="alert">
          <strong>Results changed while you were editing.</strong>
          <p>
            A proposal or evidence revision arrived from the server. Review the
            refreshed evidence before committing; your current edits have not
            been submitted.
          </p>
          <button className="text-button" type="button" onClick={reset}>
            Reset and review latest results
          </button>
        </div>
      )}
      <MutationError mutation={commit} />
      <button className="primary" disabled={commit.isPending || serverChanged}>
        {commit.isPending
          ? "Committing..."
          : proposal?.resolution?.computed_winner &&
              structuredValue(question, effectiveValue, effectiveMany) ===
                proposal.resolution.computed_value
            ? "Confirm unchanged proposal"
            : proposal
              ? proposal.resolution?.computed_winner
                ? "Commit owner override"
                : "Commit owner judgment"
              : "Commit Decision"}
      </button>
    </form>
  );
}
