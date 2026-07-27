import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { apiRequest as request } from "../apiClient";
import { MutationError } from "../MutationError";
import { QuestionDependencyEditor } from "./QuestionDependencyEditor";
import { QuestionPolicyControls } from "./QuestionPolicyControls";
import type { Dependency, Draft, Option, Question } from "./types";

export function QuestionComposer({
  askId,
  value,
  refresh,
}: {
  askId: string;
  value: Draft;
  refresh: () => Promise<unknown>;
}) {
  const [type, setType] = useState("open_question"),
    [prompt, setPrompt] = useState("");
  const [options, setOptions] = useState<Option[]>([
    { value: "yes", label: "Yes", consequence: null },
    { value: "no", label: "No", consequence: null },
  ]);
  const [dependsOn, setDependsOn] = useState<Dependency | null>(null);
  const [visibility, setVisibility] =
      useState<Question["response_visibility"]>("after_own_response"),
    [closePolicy, setClosePolicy] =
      useState<Question["close_policy"]>("either"),
    [openTo, setOpenTo] =
      useState<NonNullable<Question["open_to"]>>("assigned_only");
  const mutation = useMutation({
    mutationFn: () =>
      request<Draft>(`/api/asks/${askId}/questions`, "POST", {
        template_id: type,
        prompt,
        options: [
          "multi_pick",
          "approval",
          "directional_check",
          "decision_fork",
        ].includes(type)
          ? options
          : [],
        allow_comment: true,
        depends_on: dependsOn,
        response_visibility: visibility,
        close_policy: closePolicy,
        open_to: openTo,
        critiques_overridden: [],
      }),
    onSuccess: async () => {
      setPrompt("");
      setDependsOn(null);
      setOpenTo("assigned_only");
      await refresh();
    },
  });
  return (
    <form
      className="question-composer"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
    >
      <h3>Add a Question</h3>
      {value.status === "sent" && (
        <p className="read-only">
          The existing recipient roster is immutable. This Question is assigned
          to every current recipient; the all-responded grace period restarts
          for this Question only.
        </p>
      )}
      <label>
        <span>Format</span>
        <select
          aria-label="Question format"
          value={type}
          onChange={(e) => setType(e.target.value)}
        >
          <option value="open_question">Open text</option>
          <option value="quantity">Number</option>
          <option value="when">Date</option>
          <option value="multi_pick">Choose several</option>
          <option value="approval">Approval</option>
          <option value="directional_check">Directional check</option>
          <option value="decision_fork">Decision fork</option>
        </select>
      </label>
      <label className="wide">
        <span>Prompt</span>
        <textarea
          aria-label="Question prompt"
          required
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
      </label>
      {[
        "multi_pick",
        "approval",
        "directional_check",
        "decision_fork",
      ].includes(type) && (
        <div className="option-editor wide">
          {options.map((option, index) => (
            <div key={index}>
              <input
                aria-label={`Option ${index + 1} value`}
                value={option.value}
                onChange={(e) =>
                  setOptions(
                    options.map((item, i) =>
                      i === index ? { ...item, value: e.target.value } : item,
                    ),
                  )
                }
              />
              <input
                aria-label={`Option ${index + 1} label`}
                value={option.label}
                onChange={(e) =>
                  setOptions(
                    options.map((item, i) =>
                      i === index ? { ...item, label: e.target.value } : item,
                    ),
                  )
                }
              />
              {type === "decision_fork" && (
                <input
                  aria-label={`Option ${index + 1} consequence`}
                  placeholder="Consequence"
                  value={option.consequence ?? ""}
                  onChange={(e) =>
                    setOptions(
                      options.map((item, i) =>
                        i === index
                          ? { ...item, consequence: e.target.value }
                          : item,
                      ),
                    )
                  }
                />
              )}
            </div>
          ))}
        </div>
      )}
      <QuestionDependencyEditor
        questions={value.questions}
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
      <MutationError mutation={mutation} />
      <button className="primary" disabled={mutation.isPending}>
        {mutation.isPending ? "Adding..." : "Add Question"}
      </button>
    </form>
  );
}
