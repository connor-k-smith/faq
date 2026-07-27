import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { apiRequest as request } from "../apiClient";
import { MutationError } from "../MutationError";
import { describeDependency } from "./dependencyFormatters";
import { QuestionDependencyEditor } from "./QuestionDependencyEditor";
import { QuestionPolicyControls } from "./QuestionPolicyControls";
import type { Dependency, Draft, Question } from "./types";

export function QuestionCard({
  askId,
  question,
  questions,
  canEdit,
  canDelete,
  sent,
  refresh,
}: {
  askId: string;
  question: Question;
  questions: Question[];
  canEdit: boolean;
  canDelete: boolean;
  sent: boolean;
  refresh: () => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false),
    [prompt, setPrompt] = useState(question.prompt),
    [dependsOn, setDependsOn] = useState<Dependency | null>(
      question.depends_on,
    );
  const [visibility, setVisibility] = useState(question.response_visibility),
    [closePolicy, setClosePolicy] = useState(question.close_policy),
    [openTo, setOpenTo] = useState<NonNullable<Question["open_to"]>>(
      question.open_to ?? "assigned_only",
    );
  const remove = useMutation({
    mutationFn: () =>
      request<void>(`/api/asks/${askId}/questions/${question.id}`, "DELETE"),
    onSuccess: refresh,
  });
  const save = useMutation({
    mutationFn: () =>
      request<Draft>(`/api/asks/${askId}/questions/${question.id}`, "PUT", {
        template_id: question.template_id,
        prompt,
        help_text: question.help_text,
        allow_comment: question.allow_comment,
        depends_on: dependsOn,
        response_visibility: visibility,
        close_policy: closePolicy,
        open_to: openTo,
        options: question.options.map(({ value, label, consequence }) => ({
          value,
          label,
          consequence,
        })),
        critiques_overridden: question.critiques_overridden,
      }),
    onSuccess: async () => {
      setEditing(false);
      await refresh();
    },
  });
  const prerequisite = questions.find(
    (item) => item.id === question.depends_on?.question_id,
  );
  const cancel = () => {
    setPrompt(question.prompt);
    setDependsOn(question.depends_on);
    setVisibility(question.response_visibility);
    setClosePolicy(question.close_policy);
    setOpenTo(question.open_to ?? "assigned_only");
    setEditing(false);
  };
  return (
    <article className="question-card">
      <div className="question-number">Q{question.ordinal + 1}</div>
      <div>
        <span className="type-label">
          {question.primitive.replace("_", " ")} · v{question.version}
        </span>
        {question.supersedes_question_id && (
          <small>Corrected version. A fresh response is required.</small>
        )}
        {question.copied_from_question_id && (
          <small>Copied for delegation with dependencies cleared.</small>
        )}
        {editing ? (
          <form
            className="inline-edit"
            onSubmit={(e) => {
              e.preventDefault();
              if (
                !sent ||
                window.confirm(
                  "If anyone has answered, their response will be retained and this Question will be re-requested. Continue?",
                )
              )
                save.mutate();
            }}
          >
            <textarea
              aria-label={`Edit ${question.prompt}`}
              required
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
            <QuestionDependencyEditor
              questions={questions}
              questionId={question.id}
              value={dependsOn}
              onChange={setDependsOn}
            />
            <QuestionPolicyControls
              responseVisibility={visibility}
              closePolicy={closePolicy}
              openTo={openTo}
              onVisibility={setVisibility}
              onClosePolicy={setClosePolicy}
              onOpenTo={setOpenTo}
            />
            <button className="primary" disabled={save.isPending}>
              {save.isPending ? "Saving..." : "Save Question"}
            </button>
            <button className="text-button" type="button" onClick={cancel}>
              Cancel
            </button>
            <MutationError mutation={save} />
          </form>
        ) : (
          <>
            <h3>{question.prompt}</h3>
            {question.help_text && <p>{question.help_text}</p>}
            <small>
              {question.close_policy.replace("_", " ")} closure ·{" "}
              {question.response_visibility.replaceAll("_", " ")} responses ·{" "}
              {question.open_to === "project_members"
                ? "Project members may advise"
                : "assigned stakeholders only"}
            </small>
            {question.depends_on && (
              <p className="dependency-summary">
                Activates when Question{" "}
                {prerequisite ? prerequisite.ordinal + 1 : "?"}{" "}
                {describeDependency(question.depends_on, prerequisite)}.
              </p>
            )}
            {question.options.map((option) => (
              <div className="option-preview" key={option.id ?? option.value}>
                <i />
                {option.label}
                {option.consequence && <small>{option.consequence}</small>}
              </div>
            ))}
          </>
        )}
      </div>
      {canEdit && (
        <div className="card-actions">
          <button
            className="icon-button edit-button"
            aria-label={`Edit ${question.prompt}`}
            onClick={() => setEditing(true)}
          >
            Edit
          </button>
          {canDelete && (
            <button
              className="icon-button"
              disabled={remove.isPending}
              aria-label={`${remove.isPending ? "Deleting" : "Delete"} ${question.prompt}`}
              onClick={() =>
                window.confirm(`Delete ${question.prompt}?`) && remove.mutate()
              }
            >
              ×
            </button>
          )}
          <MutationError mutation={remove} />
        </div>
      )}
    </article>
  );
}
