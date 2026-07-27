import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { apiRequest as request } from "../apiClient";
import type { SendResult, ShareArtifact } from "../apiTypes";
import { MutationError } from "../MutationError";
import type { Draft } from "./types";
export function DraftActions({
  askId,
  value,
  refresh,
  onArtifacts,
}: {
  askId: string;
  value: Draft;
  refresh: () => Promise<unknown>;
  onArtifacts: (a: ShareArtifact[]) => void;
}) {
  const [warning, setWarning] = useState(false),
    warned = value.recipients.filter((r) => r.workload_warning);
  const cancel = useMutation({
    mutationFn: () => request<Draft>(`/api/asks/${askId}/cancel`, "POST"),
    onSuccess: refresh,
  });
  const send = useMutation({
    mutationFn: () => request<SendResult>(`/api/asks/${askId}/send`, "POST"),
    onSuccess: async (result) => {
      onArtifacts(result.artifacts);
      await refresh();
    },
  });
  if (value.status !== "draft" && value.status !== "sent") return null;
  return (
    <>
      <MutationError mutation={send} />
      <MutationError mutation={cancel} />
      <footer className="draft-footer">
        <button
          className="danger-button"
          type="button"
          disabled={cancel.isPending}
          onClick={() => window.confirm("Cancel this Ask?") && cancel.mutate()}
        >
          {cancel.isPending ? "Cancelling..." : "Cancel Ask"}
        </button>
        <span>
          {value.questions.length} questions · {value.recipients.length}{" "}
          stakeholders
        </span>
        {value.status === "draft" && (
          <div className="send-action">
            {warning && warned.length > 0 ? (
              <div className="workload-warning" role="alert">
                <strong>Recipient workload warning</strong>
                <p>
                  {warned.map((r) => r.display_name).join(", ")}{" "}
                  {warned.length === 1 ? "has" : "have"} existing or recent
                  assignments. You can still send this Ask.
                </p>
                <button
                  className="primary"
                  type="button"
                  disabled={send.isPending}
                  onClick={() => send.mutate()}
                >
                  {send.isPending ? "Preparing..." : "Send anyway"}
                </button>
              </div>
            ) : (
              <button
                className="primary"
                type="button"
                disabled={
                  send.isPending ||
                  !value.questions.length ||
                  !value.recipients.length
                }
                onClick={() => {
                  if (warned.length) setWarning(true);
                  else if (
                    window.confirm("Issue personal links and freeze this Ask?")
                  )
                    send.mutate();
                }}
              >
                {send.isPending ? "Preparing..." : "Prepare to send"}
              </button>
            )}
          </div>
        )}
      </footer>
    </>
  );
}
