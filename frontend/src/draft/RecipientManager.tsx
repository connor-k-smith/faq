import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { apiRequest as request } from "../apiClient";
import type { RecipientAddResult, ShareArtifact } from "../apiTypes";
import { MutationError } from "../MutationError";
import { RecipientCard } from "./RecipientCard";
import type { Draft, Recipient } from "./types";
export function RecipientManager({
  askId,
  value,
  refresh,
  onArtifact,
}: {
  askId: string;
  value: Draft;
  refresh: () => Promise<unknown>;
  onArtifact: (artifact: ShareArtifact) => void;
}) {
  const [recipient, setRecipient] = useState({ display_name: "", email: "" }),
    [selected, setSelected] = useState(() => value.questions.map((q) => q.id)),
    [deadline, setDeadline] = useState("");
  const previousIds = useRef(value.questions.map((q) => q.id));
  useEffect(() => {
    const next = value.questions.map((q) => q.id),
      previous = new Set(previousIds.current),
      valid = new Set(next);
    setSelected((current) => [
      ...current.filter((id) => valid.has(id)),
      ...next.filter((id) => !previous.has(id)),
    ]);
    previousIds.current = next;
  }, [value.questions]);
  const add = useMutation({
    mutationFn: () =>
      request<Recipient | RecipientAddResult>(
        `/api/asks/${askId}/recipients`,
        "POST",
        {
          display_name: recipient.display_name,
          email: recipient.email || null,
          question_ids: value.status === "sent" ? selected : null,
          replacement_deadline:
            value.status === "sent" && value.overdue ? deadline || null : null,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        },
      ),
    onSuccess: async (result) => {
      if ("artifact" in result) onArtifact(result.artifact);
      setRecipient({ display_name: "", email: "" });
      setDeadline("");
      await refresh();
    },
  });
  return (
    <aside className="recipient-column">
      <div className="section-title">
        <h2>Stakeholders</h2>
        <span>{value.recipients.length.toString().padStart(2, "0")}</span>
      </div>
      {value.recipients.map((item) => (
        <RecipientCard
          key={item.id}
          recipient={item}
          askId={askId}
          questions={value.questions}
          readOnly={value.read_only}
          refresh={refresh}
        />
      ))}
      {value.can_add_recipients && (
        <form
          className="recipient-form"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <h3>Add stakeholder</h3>
          {value.status === "sent" && (
            <>
              <p>
                This creates one new invitation without changing the existing
                roster or links.
              </p>
              <fieldset>
                <legend>Current open Questions</legend>
                {value.questions.map((q) => (
                  <label key={q.id}>
                    <input
                      type="checkbox"
                      checked={selected.includes(q.id)}
                      onChange={(e) =>
                        setSelected((current) =>
                          e.target.checked
                            ? [...current, q.id]
                            : current.filter((id) => id !== q.id),
                        )
                      }
                    />{" "}
                    {q.prompt}
                  </label>
                ))}
              </fieldset>
              {value.overdue && (
                <label>
                  <span>Replacement deadline</span>
                  <input
                    aria-label="Replacement deadline"
                    type="date"
                    required
                    value={deadline}
                    onChange={(e) => setDeadline(e.target.value)}
                  />
                  <small>
                    The passed Ask deadline must be replaced with a future date.
                  </small>
                </label>
              )}
            </>
          )}
          <label>
            <span>Display name</span>
            <input
              aria-label="Stakeholder name"
              required
              value={recipient.display_name}
              onChange={(e) =>
                setRecipient({ ...recipient, display_name: e.target.value })
              }
            />
          </label>
          <label>
            <span>
              Email <i>optional</i>
            </span>
            <input
              aria-label="Stakeholder email"
              type="email"
              value={recipient.email}
              onChange={(e) =>
                setRecipient({ ...recipient, email: e.target.value })
              }
            />
          </label>
          <MutationError mutation={add} />
          <button className="primary" disabled={add.isPending}>
            {add.isPending ? "Adding..." : "Add stakeholder"}
          </button>
        </form>
      )}
    </aside>
  );
}
