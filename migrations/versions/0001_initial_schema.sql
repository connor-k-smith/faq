CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE actor_kind AS ENUM ('human','agent');
CREATE TYPE organization_role AS ENUM ('member','admin');
CREATE TYPE contact_kind AS ENUM ('email','slack','sms','webhook');
CREATE TYPE initiative_kind AS ENUM ('feature','milestone','workstream','other');
CREATE TYPE question_primitive AS ENUM (
  'select_one','select_many','text','number','date','date_range','bool','rank','scale'
);
CREATE TYPE question_open_to AS ENUM ('assigned_only','project_members');
CREATE TYPE response_visibility AS ENUM ('immediate','after_own_response','after_close');
CREATE TYPE question_state AS ENUM ('open','closed','superseded');
CREATE TYPE question_close_policy AS ENUM ('all_responded','deadline','either');
CREATE TYPE question_origin AS ENUM ('author','agent_surfaced','agent_restructured');
CREATE TYPE outcome_effect AS ENUM ('unchanged','clarified','changed');
CREATE TYPE ask_status AS ENUM ('draft','sent','closed','cancelled');
CREATE TYPE assignment_origin AS ENUM ('assigned','unsolicited','delegated');
CREATE TYPE assignment_state AS ENUM ('blocked','pending','responded','delegated','expired','withdrawn');
CREATE TYPE response_disposition AS ENUM (
  'answered','rejected_premise','delegated','need_context','abstain'
);
CREATE TYPE response_channel AS ENUM ('web','api');
CREATE TYPE decision_state AS ENUM ('proposed','committed','superseded');
CREATE TYPE decision_basis AS ENUM (
  'unanimous','single_respondent','majority','asker_judgment','asker_override',
  'expired_no_response','revision'
);
CREATE TYPE decision_statement_source AS ENUM ('owner','deterministic','model_draft');
CREATE TYPE decision_response_role AS ENUM ('determining','context');

CREATE TABLE organization (
  id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  name text NOT NULL,
  logo_url text,
  primary_domain text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE actor (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind actor_kind NOT NULL DEFAULT 'human',
  organization_role organization_role NOT NULL DEFAULT 'member',
  display_name text NOT NULL,
  firebase_uid text UNIQUE,
  avatar_url text,
  timezone text NOT NULL DEFAULT 'UTC',
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE contact_method (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id uuid NOT NULL REFERENCES actor(id) ON DELETE CASCADE,
  kind contact_kind NOT NULL,
  value text NOT NULL,
  verified_at timestamptz,
  opted_in_at timestamptz,
  priority int NOT NULL DEFAULT 100,
  quiet_hours jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (actor_id, kind, value)
);

CREATE TABLE login_invitation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL,
  invited_by uuid NOT NULL REFERENCES actor(id),
  accepted_by uuid REFERENCES actor(id),
  expires_at timestamptz NOT NULL,
  accepted_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((accepted_by IS NULL) = (accepted_at IS NULL))
);

CREATE UNIQUE INDEX login_invitation_one_active_per_email
  ON login_invitation (lower(email)) WHERE accepted_at IS NULL AND revoked_at IS NULL;

CREATE TABLE project (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  aliases text[] NOT NULL DEFAULT '{}',
  description text,
  external_refs jsonb NOT NULL DEFAULT '{}',
  created_by uuid NOT NULL REFERENCES actor(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz
);

CREATE TABLE membership (
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  actor_id uuid NOT NULL REFERENCES actor(id) ON DELETE CASCADE,
  role text,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, actor_id)
);

CREATE TABLE initiative (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  name text NOT NULL,
  kind initiative_kind NOT NULL,
  description text,
  external_refs jsonb NOT NULL DEFAULT '{}',
  created_by uuid NOT NULL REFERENCES actor(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz,
  UNIQUE (id, project_id),
  FOREIGN KEY (project_id, created_by) REFERENCES membership(project_id, actor_id)
);

CREATE UNIQUE INDEX initiative_active_name
  ON initiative (project_id, lower(name)) WHERE archived_at IS NULL;

CREATE TABLE question_template (
  id text PRIMARY KEY,
  primitive question_primitive NOT NULL,
  label text NOT NULL,
  description text,
  default_options jsonb NOT NULL DEFAULT '[]',
  default_validation jsonb NOT NULL DEFAULT '{}',
  requires_consequence bool NOT NULL DEFAULT false,
  auto_commit bool NOT NULL DEFAULT false,
  default_auto_commit_if jsonb,
  default_require_comment_if jsonb,
  renderer text NOT NULL DEFAULT 'default',
  builtin bool NOT NULL DEFAULT true
);

CREATE TABLE question (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  template_id text NOT NULL REFERENCES question_template(id),
  primitive question_primitive NOT NULL,
  version int NOT NULL DEFAULT 1,
  supersedes_question_id uuid,
  copied_from_question_id uuid,
  state question_state NOT NULL DEFAULT 'open',
  origin question_origin NOT NULL DEFAULT 'author',
  prompt text NOT NULL,
  help_text text,
  context_refs jsonb NOT NULL DEFAULT '[]',
  open_to question_open_to NOT NULL DEFAULT 'assigned_only',
  allow_comment bool NOT NULL DEFAULT true,
  validation jsonb NOT NULL DEFAULT '{}',
  require_comment_if jsonb,
  depends_on jsonb,
  response_visibility response_visibility NOT NULL DEFAULT 'after_own_response',
  anonymous bool NOT NULL DEFAULT false,
  proposed_value jsonb,
  proposed_rationale text,
  close_policy question_close_policy NOT NULL DEFAULT 'either',
  auto_commit bool NOT NULL,
  auto_commit_if jsonb,
  created_by uuid NOT NULL REFERENCES actor(id),
  critiques_overridden jsonb NOT NULL DEFAULT '[]',
  close_eligible_at timestamptz,
  closed_at timestamptz,
  outcome_effect outcome_effect,
  outcome_effect_note text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, project_id),
  FOREIGN KEY (project_id, created_by) REFERENCES membership(project_id, actor_id),
  FOREIGN KEY (supersedes_question_id, project_id) REFERENCES question(id, project_id),
  FOREIGN KEY (copied_from_question_id, project_id) REFERENCES question(id, project_id)
);

CREATE TABLE question_option (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  question_id uuid NOT NULL REFERENCES question(id) ON DELETE CASCADE,
  ordinal int NOT NULL,
  value text NOT NULL,
  label text NOT NULL,
  consequence text,
  triggers jsonb NOT NULL DEFAULT '[]',
  search_tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('english', coalesce(label,'') || ' ' || coalesce(consequence,''))
  ) STORED,
  UNIQUE (question_id, value)
);

CREATE TABLE ask (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  initiative_id uuid NOT NULL,
  parent_ask_id uuid,
  title text NOT NULL,
  intro text,
  created_by uuid NOT NULL REFERENCES actor(id),
  deadline timestamptz,
  default_note text,
  status ask_status NOT NULL DEFAULT 'draft',
  owner_id uuid NOT NULL REFERENCES actor(id),
  sent_at timestamptz,
  closed_at timestamptz,
  share_message text,
  critiques_overridden jsonb NOT NULL DEFAULT '[]',
  search_tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('english', coalesce(title,'') || ' ' || coalesce(intro,''))
  ) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, project_id),
  FOREIGN KEY (project_id, created_by) REFERENCES membership(project_id, actor_id),
  FOREIGN KEY (project_id, owner_id) REFERENCES membership(project_id, actor_id),
  FOREIGN KEY (initiative_id, project_id) REFERENCES initiative(id, project_id),
  FOREIGN KEY (parent_ask_id, project_id) REFERENCES ask(id, project_id)
);

CREATE TABLE ask_recipient (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  ask_id uuid NOT NULL,
  actor_id uuid NOT NULL REFERENCES actor(id),
  display_name text NOT NULL,
  token_hash text UNIQUE,
  token_issued_at timestamptz,
  session_version int NOT NULL DEFAULT 1,
  revoked_at timestamptz,
  access_expires_at timestamptz,
  share_marked_sent_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (ask_id, actor_id),
  UNIQUE (id, ask_id, project_id, actor_id),
  FOREIGN KEY (ask_id, project_id) REFERENCES ask(id, project_id) ON DELETE CASCADE,
  CHECK (
    (token_hash IS NULL AND token_issued_at IS NULL AND access_expires_at IS NULL) OR
    (token_hash IS NOT NULL AND token_issued_at IS NOT NULL AND access_expires_at IS NOT NULL)
  )
);

CREATE TABLE ask_question (
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  ask_id uuid NOT NULL,
  question_id uuid NOT NULL,
  ordinal int NOT NULL,
  superseded_at timestamptz,
  PRIMARY KEY (ask_id, question_id),
  UNIQUE (question_id),
  UNIQUE (ask_id, question_id, project_id),
  FOREIGN KEY (ask_id, project_id) REFERENCES ask(id, project_id) ON DELETE CASCADE,
  FOREIGN KEY (question_id, project_id) REFERENCES question(id, project_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ask_question_active_ordinal
  ON ask_question (ask_id, ordinal) WHERE superseded_at IS NULL;

CREATE TABLE assignment (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  ask_id uuid NOT NULL,
  question_id uuid NOT NULL,
  actor_id uuid NOT NULL REFERENCES actor(id),
  ask_recipient_id uuid,
  origin assignment_origin NOT NULL DEFAULT 'assigned',
  state assignment_state NOT NULL DEFAULT 'pending',
  delegated_to_actor_id uuid REFERENCES actor(id),
  child_ask_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (ask_id, question_id, actor_id),
  UNIQUE (id, ask_id, question_id, project_id),
  FOREIGN KEY (ask_id, question_id, project_id)
    REFERENCES ask_question(ask_id, question_id, project_id) ON DELETE CASCADE,
  FOREIGN KEY (ask_recipient_id, ask_id, project_id, actor_id)
    REFERENCES ask_recipient(id, ask_id, project_id, actor_id),
  FOREIGN KEY (child_ask_id, project_id) REFERENCES ask(id, project_id),
  CHECK (
    (origin = 'unsolicited' AND ask_recipient_id IS NULL) OR
    (origin <> 'unsolicited' AND ask_recipient_id IS NOT NULL)
  )
);

CREATE TABLE response (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assignment_id uuid NOT NULL REFERENCES assignment(id) ON DELETE CASCADE,
  submission_id uuid NOT NULL,
  version int NOT NULL DEFAULT 1,
  disposition response_disposition NOT NULL DEFAULT 'answered',
  value jsonb,
  comment text,
  delegated_to_actor_id uuid REFERENCES actor(id),
  answered_via response_channel NOT NULL DEFAULT 'web',
  provenance jsonb NOT NULL DEFAULT '{}',
  search_tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('english', coalesce(value::text,'') || ' ' || coalesce(comment,''))
  ) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (assignment_id, version),
  UNIQUE (assignment_id, submission_id),
  UNIQUE (id, assignment_id)
);

CREATE TABLE decision (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  question_id uuid NOT NULL,
  ask_id uuid NOT NULL,
  state decision_state NOT NULL DEFAULT 'proposed',
  basis decision_basis NOT NULL,
  value jsonb,
  statement text,
  statement_source decision_statement_source,
  decided_by uuid REFERENCES actor(id),
  supersedes_decision_id uuid,
  provenance jsonb NOT NULL DEFAULT '{}',
  shared_with_recipients_at timestamptz,
  search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(statement,''))) STORED,
  committed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, project_id),
  UNIQUE (id, ask_id, question_id, project_id),
  FOREIGN KEY (ask_id, question_id, project_id)
    REFERENCES ask_question(ask_id, question_id, project_id),
  FOREIGN KEY (project_id, decided_by) REFERENCES membership(project_id, actor_id),
  FOREIGN KEY (supersedes_decision_id, project_id) REFERENCES decision(id, project_id),
  CHECK (
    state <> 'committed' OR
    (statement IS NOT NULL AND statement_source IN ('owner','deterministic') AND committed_at IS NOT NULL)
  )
);

CREATE UNIQUE INDEX decision_one_committed_per_question
  ON decision (question_id) WHERE state = 'committed';
CREATE UNIQUE INDEX decision_one_proposed_per_question
  ON decision (question_id) WHERE state = 'proposed';

CREATE TABLE decision_response (
  decision_id uuid NOT NULL,
  response_id uuid NOT NULL,
  assignment_id uuid NOT NULL,
  project_id uuid NOT NULL,
  ask_id uuid NOT NULL,
  question_id uuid NOT NULL,
  role decision_response_role NOT NULL DEFAULT 'determining',
  PRIMARY KEY (decision_id, response_id),
  FOREIGN KEY (decision_id, ask_id, question_id, project_id)
    REFERENCES decision(id, ask_id, question_id, project_id) ON DELETE CASCADE,
  FOREIGN KEY (response_id, assignment_id) REFERENCES response(id, assignment_id),
  FOREIGN KEY (assignment_id, ask_id, question_id, project_id)
    REFERENCES assignment(id, ask_id, question_id, project_id)
);

CREATE TABLE authoring_session (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  actor_id uuid NOT NULL,
  ask_id uuid,
  conversation_id text,
  messages jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (project_id, actor_id) REFERENCES membership(project_id, actor_id),
  FOREIGN KEY (ask_id, project_id) REFERENCES ask(id, project_id) ON DELETE CASCADE
);

CREATE TABLE event (
  id bigserial PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  project_id uuid REFERENCES project(id) ON DELETE SET NULL,
  ask_id uuid REFERENCES ask(id) ON DELETE SET NULL,
  question_id uuid REFERENCES question(id) ON DELETE SET NULL,
  assignment_id uuid REFERENCES assignment(id) ON DELETE SET NULL,
  ask_recipient_id uuid REFERENCES ask_recipient(id) ON DELETE SET NULL,
  actor_id uuid REFERENCES actor(id) ON DELETE SET NULL,
  type text NOT NULL,
  data jsonb NOT NULL DEFAULT '{}',
  ip inet,
  user_agent text
);

CREATE INDEX event_project_at_idx ON event (project_id, at DESC);
CREATE INDEX event_type_at_idx ON event (type, at DESC);
CREATE INDEX event_ask_at_idx ON event (ask_id, at DESC);
CREATE INDEX assignment_recipient_state_idx ON assignment (ask_recipient_id, state);
CREATE INDEX assignment_actor_state_idx ON assignment (actor_id, state);
CREATE INDEX assignment_ask_question_idx ON assignment (ask_id, question_id);
CREATE INDEX decision_project_committed_idx
  ON decision (project_id, committed_at DESC) WHERE state = 'committed';
CREATE INDEX question_close_eligible_idx
  ON question (close_eligible_at) WHERE state = 'open';
CREATE INDEX question_state_policy_idx ON question (state, close_policy);
CREATE INDEX ask_deadline_idx ON ask (deadline) WHERE status = 'sent';
CREATE INDEX decision_search_idx ON decision USING gin (search_tsv);
CREATE INDEX ask_search_idx ON ask USING gin (search_tsv);
CREATE INDEX question_search_idx ON question USING gin (
  to_tsvector('english', coalesce(prompt,'') || ' ' || coalesce(help_text,''))
);
CREATE INDEX question_option_search_idx ON question_option USING gin (search_tsv);
CREATE INDEX response_search_idx ON response USING gin (search_tsv);
CREATE INDEX response_assignment_version_idx ON response (assignment_id, version DESC);
CREATE INDEX contact_method_actor_idx ON contact_method (actor_id);
CREATE INDEX ask_recipient_actor_created_idx ON ask_recipient (actor_id, created_at DESC);
CREATE INDEX ask_initiative_created_idx ON ask (initiative_id, created_at DESC);
CREATE INDEX question_project_state_idx ON question (project_id, state);

INSERT INTO question_template (
  id, primitive, label, default_options, default_validation, requires_consequence,
  auto_commit, default_auto_commit_if, default_require_comment_if
) VALUES
  (
    'directional_check', 'select_one', 'Directional check',
    '[{"value":"yes","label":"Yes, directionally right"},{"value":"mostly","label":"Mostly - needs corrections"},{"value":"no","label":"No, this misses it"}]',
    '{}', false, true, '{"op":"eq","value":"yes"}', '{"op":"neq","value":"yes"}'
  ),
  (
    'assertion', 'select_one', 'Assertion',
    '[{"value":"confirm","label":"Confirm"},{"value":"partially","label":"Partially correct"},{"value":"reject","label":"Reject"}]',
    '{}', false, true, '{"op":"eq","value":"confirm"}', null
  ),
  (
    'approval', 'select_one', 'Approval',
    '[{"value":"approve","label":"Approve"},{"value":"reject","label":"Reject"}]',
    '{}', false, true, null, null
  ),
  ('decision_fork', 'select_one', 'Decision fork', '[]', '{}', true, true, null, null),
  (
    'sla', 'select_one', 'Turnaround time',
    '[{"value":"minutes","label":"Minutes"},{"value":"same_day","label":"Same day"},{"value":"2_3_days","label":"2-3 days"},{"value":"this_week","label":"This week"},{"value":"no_rush","label":"No rush"}]',
    '{}', false, false, null, null
  ),
  ('open_question', 'text', 'Open question', '[]', '{"min_length":1}', false, false, null, null),
  ('multi_pick', 'select_many', 'Choose several', '[]', '{}', false, false, null, null),
  ('quantity', 'number', 'Quantity', '[]', '{}', false, false, null, null),
  ('when', 'date', 'Date', '[]', '{}', false, false, null, null);
