import type { Question } from "./types";
export function QuestionPolicyControls({
  responseVisibility,
  closePolicy,
  openTo,
  onVisibility,
  onClosePolicy,
  onOpenTo,
}: {
  responseVisibility: Question["response_visibility"];
  closePolicy: Question["close_policy"];
  openTo: NonNullable<Question["open_to"]>;
  onVisibility: (v: Question["response_visibility"]) => void;
  onClosePolicy: (v: Question["close_policy"]) => void;
  onOpenTo: (v: NonNullable<Question["open_to"]>) => void;
}) {
  return (
    <fieldset className="wide">
      <legend>Response and closure</legend>
      <label>
        <span>Response visibility</span>
        <select
          aria-label="Response visibility"
          value={responseVisibility}
          onChange={(e) =>
            onVisibility(e.target.value as Question["response_visibility"])
          }
        >
          <option value="after_own_response">
            After collaborator responds
          </option>
          <option value="after_close">After Question closes</option>
          <option value="immediate">Immediately</option>
        </select>
      </label>
      <label>
        <span>Close policy</span>
        <select
          aria-label="Close policy"
          value={closePolicy}
          onChange={(e) =>
            onClosePolicy(e.target.value as Question["close_policy"])
          }
        >
          <option value="either">All respond or deadline</option>
          <option value="all_responded">All respond</option>
          <option value="deadline">Deadline</option>
        </select>
      </label>
      <label>
        <span>Who may contribute</span>
        <select
          aria-label="Who may contribute"
          value={openTo}
          onChange={(e) =>
            onOpenTo(e.target.value as NonNullable<Question["open_to"]>)
          }
        >
          <option value="assigned_only">Assigned stakeholders only</option>
          <option value="project_members">Project members may advise</option>
        </select>
        <small>
          Member contributions are advisory and never determine resolution.
        </small>
      </label>
    </fieldset>
  );
}
