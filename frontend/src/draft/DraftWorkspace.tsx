import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiRequest as request } from "../apiClient";
import type { ShareArtifact } from "../apiTypes";
import { AssistantAuthoringPanel } from "./AssistantAuthoringPanel";
import { DraftActions } from "./DraftActions";
import { DraftMetadataForm, type DraftMetadata } from "./DraftMetadataForm";
import { DraftStatus } from "./DraftStatus";
import { QuestionCard } from "./QuestionCard";
import { QuestionComposer } from "./QuestionComposer";
import { RecipientManager } from "./RecipientManager";
import { SharePanel } from "./SharePanel";
import type { Draft } from "./types";

export function DraftEditor({ askId }: { askId: string }) {
  const draft = useQuery({
    queryKey: ["ask", askId],
    queryFn: () => request<Draft>(`/api/asks/${askId}`),
  });

  if (draft.isPending) return <DraftStatus text="Opening draft" pending />;
  if (draft.isError || !draft.data) {
    return (
      <DraftStatus text="Draft unavailable" detail={draft.error?.message} />
    );
  }
  return <DraftWorkspace askId={askId} value={draft.data} />;
}

export function DraftWorkspace({
  askId,
  value,
}: {
  askId: string;
  value: Draft;
}) {
  const client = useQueryClient();
  const [metadata, setMetadata] = useState<DraftMetadata>({
    title: value.title,
    intro: value.intro ?? "",
    deadline: value.deadline_date ?? "",
    default_note: value.default_note ?? "",
  });
  const [artifacts, setArtifacts] = useState<ShareArtifact[]>([]);
  const refresh = () => client.invalidateQueries({ queryKey: ["ask", askId] });
  const save = useMutation({
    mutationFn: () =>
      request<Draft>(`/api/asks/${askId}`, "PUT", {
        ...metadata,
        deadline: metadata.deadline || null,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        critiques_overridden: value.critiques_overridden,
      }),
    onSuccess: refresh,
  });
  const onArtifact = (artifact: ShareArtifact) => {
    setArtifacts((items) => [
      ...items.filter((item) => item.recipient_id !== artifact.recipient_id),
      artifact,
    ]);
  };
  const correction = value.questions.some(
    (question) => question.supersedes_question_id,
  );

  return (
    <div className="author-shell">
      <header className="author-topbar">
        <a className="wordmark" href="/">
          FAQ
        </a>
        <nav aria-label="Ask breadcrumb">
          <a href={`/p/${value.project.id}`}>{value.project.name}</a>
          <span>/</span>
          <a href={`/p/${value.project.id}/i/${value.initiative.id}`}>
            {value.initiative.name}
          </a>
          <span>/</span>
          <strong>{value.title}</strong>
        </nav>
        <span className="draft-state">{value.status}</span>
      </header>
      <main className="author-main">
        {value.parent_ask_id && (
          <section
            className="lineage-notice"
            aria-label={correction ? "Correction Ask" : "Delegated Ask"}
          >
            <p className="eyebrow">
              {correction ? "Correction successor" : "Delegated snapshot"}
            </p>
            <h2>
              {correction
                ? "This draft corrects a closed Decision."
                : "This Ask contains a copied Question."}
            </h2>
            <p>
              {correction
                ? "It starts a new response cycle while the prior Ask remains closed and readable. Recipients and sending are managed normally."
                : "It was created for the delegated stakeholder as an independent snapshot. Activation dependencies were cleared; parent responses, comments, and stakeholders are not included here."}
            </p>
            <a className="text-button" href={`/a/${value.parent_ask_id}`}>
              Back to parent Ask
            </a>
          </section>
        )}
        <section className="author-intro">
          <p className="eyebrow">Agent-assisted or manual</p>
          <h1>Shape the Ask.</h1>
          <p className="lede">
            Make the question easy to answer before making it easy to send.
          </p>
        </section>
        <AssistantAuthoringPanel
          askId={askId}
          value={value}
          metadata={metadata}
          setMetadata={setMetadata}
          refresh={refresh}
        />
        <DraftMetadataForm
          value={value}
          metadata={metadata}
          setMetadata={setMetadata}
          save={save}
        />
        <div className="author-grid">
          <section>
            <div className="section-title">
              <h2>Questions</h2>
              <span>{value.questions.length.toString().padStart(2, "0")}</span>
            </div>
            <div className="question-stack">
              {value.questions.map((question) => (
                <QuestionCard
                  key={question.id}
                  askId={askId}
                  question={question}
                  questions={value.questions}
                  canEdit={value.can_edit_questions}
                  canDelete={!value.read_only}
                  sent={value.status === "sent"}
                  refresh={refresh}
                />
              ))}
            </div>
            {value.can_add_questions && (
              <QuestionComposer askId={askId} value={value} refresh={refresh} />
            )}
          </section>
          <RecipientManager
            askId={askId}
            value={value}
            refresh={refresh}
            onArtifact={onArtifact}
          />
        </div>
        <SharePanel
          askId={askId}
          value={value}
          artifacts={artifacts}
          refresh={refresh}
          onArtifact={onArtifact}
        />
        <DraftActions
          askId={askId}
          value={value}
          refresh={refresh}
          onArtifacts={setArtifacts}
        />
      </main>
    </div>
  );
}
