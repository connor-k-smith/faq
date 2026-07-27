import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { apiRequest as request } from "../apiClient";
import type { ShareArtifact } from "../apiTypes";
import { MutationError } from "../MutationError";
import type { Recipient } from "./types";
export function RecipientShare({
  askId,
  recipient,
  artifact,
  refresh,
  onArtifact,
}: {
  askId: string;
  recipient: Recipient;
  artifact?: ShareArtifact;
  refresh: () => Promise<unknown>;
  onArtifact: (a: ShareArtifact) => void;
}) {
  const [copyStatus, setCopyStatus] = useState("");
  const reissue = useMutation({
    mutationFn: () =>
      request<ShareArtifact>(
        `/api/asks/${askId}/recipients/${recipient.id}/reissue`,
        "POST",
      ),
    onSuccess: onArtifact,
  });
  const checklist = useMutation({
    mutationFn: (sent: boolean) =>
      request<Recipient>(
        `/api/asks/${askId}/recipients/${recipient.id}/checklist`,
        "PUT",
        { sent },
      ),
    onSuccess: refresh,
  });
  const revoke = useMutation({
    mutationFn: () =>
      request<void>(`/api/asks/${askId}/recipients/${recipient.id}`, "DELETE"),
    onSuccess: refresh,
  });
  const revokeButton = (
    <button
      className="danger-button"
      type="button"
      disabled={revoke.isPending}
      onClick={() =>
        window.confirm(`Revoke ${recipient.display_name}'s access?`) &&
        revoke.mutate()
      }
    >
      Revoke access
    </button>
  );
  return (
    <article className="share-card">
      <div>
        <strong>{recipient.display_name}</strong>
        <small>
          {recipient.share_marked_sent_at
            ? "Marked sent"
            : "Not yet marked sent"}
        </small>
      </div>
      <label className="sent-check">
        <input
          type="checkbox"
          disabled={checklist.isPending}
          aria-label={`Mark ${recipient.display_name} sent`}
          checked={Boolean(recipient.share_marked_sent_at)}
          onChange={(e) => checklist.mutate(e.target.checked)}
        />{" "}
        Sent
      </label>
      {artifact ? (
        <>
          <textarea
            aria-label={`Share copy for ${recipient.display_name}`}
            readOnly
            value={artifact.message}
          />
          <div className="share-actions">
            <button
              className="primary"
              type="button"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(artifact.message);
                  setCopyStatus("Message copied.");
                } catch {
                  setCopyStatus(
                    "Copy failed. Select the message and copy it manually.",
                  );
                }
              }}
            >
              Copy message
            </button>
            <button
              className="text-button"
              type="button"
              disabled={reissue.isPending}
              onClick={() => reissue.mutate()}
            >
              {reissue.isPending ? "Reissuing..." : "Reissue link"}
            </button>
            {revokeButton}
          </div>
        </>
      ) : (
        <div className="missing-artifact">
          <p>
            The raw link is only shown when issued. Reissue to create fresh
            share copy.
          </p>
          <button
            className="text-button"
            type="button"
            disabled={reissue.isPending}
            onClick={() => reissue.mutate()}
          >
            {reissue.isPending ? "Reissuing..." : "Reissue link"}
          </button>
          {revokeButton}
        </div>
      )}
      {copyStatus && <p role="status">{copyStatus}</p>}
      <MutationError mutation={checklist} />
      <MutationError mutation={reissue} />
      <MutationError mutation={revoke} />
    </article>
  );
}
