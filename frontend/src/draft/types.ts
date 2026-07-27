import type {
  AskAggregate,
  AssistantResult,
  DraftQuestion,
  DraftRecipient,
} from "../apiTypes";

export type Option = {
  id?: string;
  value: string;
  label: string;
  consequence: string | null;
};

export type DependencyOperator =
  | "eq"
  | "neq"
  | "in"
  | "not_in"
  | "answered"
  | "unanswered";

export type Dependency = {
  question_id: string;
  op: DependencyOperator;
  value?: string | string[];
};

export type Question = Omit<DraftQuestion, "depends_on"> & {
  depends_on: Dependency | null;
};
export type Recipient = DraftRecipient;
export type Draft = Omit<AskAggregate, "questions"> & { questions: Question[] };
export type Critique = NonNullable<AssistantResult["critiques"]>[number];
