import type { components } from "./api-schema";
import type { paths } from "./api-schema";

export type ApiSchema = components["schemas"];
export type Session = ApiSchema["ActorResponse"];
export type AuthConfig = ApiSchema["AuthConfigResponse"];
export type Project = ApiSchema["ProjectSummary"];
export type Landing = ApiSchema["ProjectLanding"];
export type Initiative = ApiSchema["InitiativeSummary"];
export type InboxPage = ApiSchema["InboxPage"];
export type FeedPage = ApiSchema["FeedPage"];
export type AdminAccess = ApiSchema["AccessOverview"];
export type AskAggregate = ApiSchema["AskAggregate"];
export type AskResults = ApiSchema["AskResults"];
export type DraftQuestion = AskAggregate["questions"][number];
export type DraftRecipient = AskAggregate["recipients"][number];
export type ResultQuestion = AskResults["questions"][number];
export type ResultAssignment = ResultQuestion["assignments"][number];
export type ResponseRevision = ApiSchema["ResponseRevisionDto"];
export type AssistantResult = ApiSchema["AssistantResponse"];
export type ShareArtifact = ApiSchema["ShareArtifact"];
export type SendResult = ApiSchema["SendResult"];
export type RecipientAddResult = ApiSchema["RecipientAddResult"];

type JsonBody<Path extends keyof paths, Method extends keyof paths[Path]> =
  paths[Path][Method] extends {
    requestBody: { content: { "application/json": infer Body } };
  }
    ? Body
    : never;

export type AskUpdateBody = JsonBody<"/api/asks/{ask_id}", "put">;
export type QuestionWriteBody = JsonBody<"/api/asks/{ask_id}/questions", "post">;
export type RecipientWriteBody = JsonBody<"/api/asks/{ask_id}/recipients", "post">;
export type DecisionWriteBody = JsonBody<"/api/asks/{ask_id}/questions/{question_id}/decision", "post">;
export type AdvisoryResponseWriteBody = JsonBody<"/api/asks/{ask_id}/questions/{question_id}/advisory-responses", "post">;
export type OutcomeEffectWriteBody = JsonBody<"/api/asks/{ask_id}/questions/{question_id}/outcome-effect", "post">;
