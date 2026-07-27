import type { ShareArtifact } from "../apiTypes";
import { RecipientShare } from "./RecipientShare";
import type { Draft } from "./types";
export function SharePanel({
  askId,
  value,
  artifacts,
  refresh,
  onArtifact,
}: {
  askId: string;
  value: Draft;
  artifacts: ShareArtifact[];
  refresh: () => Promise<unknown>;
  onArtifact: (a: ShareArtifact) => void;
}) {
  if (value.status !== "sent") return null;
  return (
    <section className="send-panel" aria-labelledby="share-title">
      <div className="send-heading">
        <div>
          <p className="eyebrow">Ready to deliver</p>
          <h2 id="share-title">Share each personal invitation.</h2>
        </div>
        <a className="primary" href={`/a/${askId}`}>
          View live results
        </a>
      </div>
      <p>
        Links belong to one stakeholder. Mark each invitation sent after pasting
        it into Slack or email.
      </p>
      {value.recipients.map((recipient) => (
        <RecipientShare
          key={recipient.id}
          askId={askId}
          recipient={recipient}
          artifact={artifacts.find((a) => a.recipient_id === recipient.id)}
          refresh={refresh}
          onArtifact={onArtifact}
        />
      ))}
      {artifacts.length === 0 && (
        <p className="empty">
          Invitation links are shown only once, immediately after issue or
          reissue.
        </p>
      )}
    </section>
  );
}
