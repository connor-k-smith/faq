import type { UseMutationResult } from "@tanstack/react-query";
import { MutationError } from "../MutationError";
import type { Draft } from "./types";

export type DraftMetadata = {
  title: string;
  intro: string;
  deadline: string;
  default_note: string;
};

type Props = {
  value: Draft;
  metadata: DraftMetadata;
  setMetadata: (value: DraftMetadata) => void;
  save: UseMutationResult<Draft, Error, void>;
};

export function DraftMetadataForm({
  value,
  metadata,
  setMetadata,
  save,
}: Props) {
  if (value.read_only)
    return <p className="read-only">This Ask is read only.</p>;

  return (
    <form
      className="metadata-panel"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <label>
        <span>Ask title</span>
        <input
          aria-label="Ask title"
          required
          value={metadata.title}
          onChange={(event) =>
            setMetadata({ ...metadata, title: event.target.value })
          }
        />
      </label>
      <label>
        <span>Deadline</span>
        <input
          aria-label="Deadline"
          type="date"
          value={metadata.deadline}
          onChange={(event) =>
            setMetadata({ ...metadata, deadline: event.target.value })
          }
        />
        <small>Closes at 5:00 PM in {value.owner_timezone}.</small>
      </label>
      <label className="wide">
        <span>Framing for stakeholders</span>
        <textarea
          aria-label="Framing for stakeholders"
          value={metadata.intro}
          onChange={(event) =>
            setMetadata({ ...metadata, intro: event.target.value })
          }
        />
      </label>
      <label className="wide">
        <span>Default note</span>
        <input
          aria-label="Default note"
          value={metadata.default_note}
          onChange={(event) =>
            setMetadata({ ...metadata, default_note: event.target.value })
          }
        />
      </label>
      <MutationError mutation={save} />
      <button className="primary" disabled={save.isPending}>
        Save details
      </button>
    </form>
  );
}
