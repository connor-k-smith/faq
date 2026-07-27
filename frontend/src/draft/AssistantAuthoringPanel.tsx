import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { apiRequest as request } from "../apiClient";
import type { AssistantResult } from "../apiTypes";
import { MutationError } from "../MutationError";
import type { Critique, Draft } from "./types";
import type { DraftMetadata } from "./DraftMetadataForm";

export function AssistantAuthoringPanel({
  askId,
  value,
  metadata,
  setMetadata,
  refresh,
}: {
  askId: string;
  value: Draft;
  metadata: DraftMetadata;
  setMetadata: (v: DraftMetadata) => void;
  refresh: () => Promise<unknown>;
}) {
  const [source, setSource] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [clarification, setClarification] =
    useState<AssistantResult["clarification"]>(null);
  const [critiques, setCritiques] = useState<Critique[]>([]);
  const generate = useMutation({
    mutationFn: () =>
      request<AssistantResult>(`/api/asks/${askId}/assistant`, "POST", {
        source,
        authoring_session_id: sessionId,
      }),
    onSuccess: async (result) => {
      setSessionId(result.authoring_session_id);
      setClarification(result.clarification);
      setCritiques(result.critiques ?? []);
      setSource("");
      if (result.kind === "draft" && result.draft) {
        setMetadata({
          title: result.draft.title,
          intro: result.draft.intro ?? "",
          deadline: result.draft.deadline_date ?? "",
          default_note: result.draft.default_note ?? "",
        });
        await refresh();
      }
    },
  });
  const ignore = useMutation({
    mutationFn: (critique: Critique) =>
      request<Draft>(`/api/asks/${askId}`, "PUT", {
        ...metadata,
        deadline: metadata.deadline || null,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        critiques_overridden: [...value.critiques_overridden, critique],
      }),
    onSuccess: async (_draft, critique) => {
      setCritiques((items) => items.filter((item) => item !== critique));
      await refresh();
    },
  });
  if (value.status !== "draft" || value.read_only) return null;
  return (
    <>
      <section className="assistant-panel" aria-labelledby="assistant-title">
        <div>
          <p className="eyebrow">Paste a dump</p>
          <h2 id="assistant-title">Turn rough context into Questions.</h2>
          <p>
            Paste notes, a Slack message, or the decision you are trying to
            make. Nothing is filed outside the selected Project and Initiative.
          </p>
        </div>
        {clarification && (
          <div className="clarification" role="status">
            <strong>The agent needs one detail</strong>
            <p>{clarification.question}</p>
            <small>{clarification.reason}</small>
          </div>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            generate.mutate();
          }}
        >
          <label>
            <span>{clarification ? "Your answer" : "Source material"}</span>
            <textarea
              aria-label={
                clarification ? "Clarification answer" : "Source material"
              }
              required
              value={source}
              onChange={(e) => setSource(e.target.value)}
              placeholder={
                clarification
                  ? "Answer the question above"
                  : "Paste the messy version here..."
              }
            />
          </label>
          <MutationError mutation={generate} />
          <button className="primary" disabled={generate.isPending}>
            {generate.isPending
              ? "Interrogating..."
              : clarification
                ? "Continue draft"
                : "Draft with agent"}
          </button>
        </form>
      </section>
      {critiques.length > 0 && (
        <section className="critique-panel" aria-label="Draft critiques">
          <p className="eyebrow">Review before send</p>
          {critiques.map((critique, index) => (
            <div key={`${critique.code}-${index}`}>
              <strong>{critique.code.replaceAll("_", " ")}</strong>
              <span>{critique.message}</span>
              <button
                className="text-button"
                type="button"
                onClick={() => ignore.mutate(critique)}
              >
                Ignore
              </button>
            </div>
          ))}
        </section>
      )}
    </>
  );
}
