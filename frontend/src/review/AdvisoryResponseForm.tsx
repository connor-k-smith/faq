import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiRequest as request } from "../apiClient";
import { MutationError } from "../MutationError";
import type { Question, Revision } from "./types";
export function AdvisoryResponseForm({
  askId,
  question,
}: {
  askId: string;
  question: Question;
}) {
  const client = useQueryClient(),
    [value, setValue] = useState(""),
    [many, setMany] = useState<string[]>([]),
    [comment, setComment] = useState("");
  const submit = useMutation({
    mutationFn: () =>
      request<Revision>(
        `/api/asks/${askId}/questions/${question.id}/advisory-responses`,
        "POST",
        {
          disposition: "answered",
          value:
            question.primitive === "select_many"
              ? many
              : question.primitive === "number"
                ? Number(value)
                : value,
          comment: comment || null,
          submission_id: crypto.randomUUID(),
        },
      ),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["ask-results", askId] }),
  });
  return (
    <form
      className="advisory-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit.mutate();
      }}
    >
      <div>
        <p className="eyebrow">Not assigned to you · you can still weigh in</p>
        <h3>Add advisory input</h3>
        <p>
          This attributed response will not count toward closure, quorum,
          majority, or auto-commit.
          {question.state === "closed"
            ? " Because this Question is closed, it will also be marked late."
            : ""}
        </p>
      </div>
      {question.primitive === "select_one" ? (
        <label>
          <span>Advisory response</span>
          <select
            required
            aria-label="Advisory response"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          >
            <option value="">Choose an option</option>
            {question.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      ) : question.primitive === "select_many" ? (
        <fieldset>
          <legend>Advisory response</legend>
          {question.options.map((o) => (
            <label key={o.value}>
              <input
                type="checkbox"
                checked={many.includes(o.value)}
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
      ) : (
        <label>
          <span>Advisory response</span>
          <input
            aria-label="Advisory response"
            required
            type={
              question.primitive === "number"
                ? "number"
                : question.primitive === "date"
                  ? "date"
                  : "text"
            }
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
      )}
      <label className="wide">
        <span>
          Comment <i>optional</i>
        </span>
        <textarea
          aria-label="Advisory comment"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      </label>
      <MutationError mutation={submit} />
      <button
        className="primary"
        disabled={
          submit.isPending ||
          (question.primitive === "select_many" && !many.length)
        }
      >
        {submit.isPending
          ? "Adding..."
          : question.state === "closed"
            ? "Add late advisory response"
            : "Add advisory response"}
      </button>
    </form>
  );
}
