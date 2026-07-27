export function projectFixture() {
  return {
    id: "project-1",
    name: "Atlas",
    description: "Pool platform",
    archived: false,
  };
}

export function landingFixture() {
  return {
    project: projectFixture(),
    read_only: false,
    initiatives: [
      {
        id: "initiative-1",
        name: "Pool matching",
        kind: "feature",
        description: "Define the desired matching state.",
        archived: false,
        read_only: false,
        unresolved_count: 1,
        latest_activity_at: "2026-07-25T17:00:00Z",
        asks: [
          {
            id: "ask-1",
            title: "Confirm desired state",
            status: "sent",
            created_at: "2026-07-25T17:00:00Z",
          },
        ],
        recent_decisions: [],
      },
    ],
  };
}

export function draftFixture() {
  return {
    id: "ask-1",
    project_id: "project-1",
    initiative_id: "initiative-1",
    title: "Confirm desired state",
    intro: "Check the matching model.",
    deadline: null,
    deadline_date: null,
    default_note: null,
    status: "draft",
    owner_id: "owner-1",
    critiques_overridden: [],
    created_at: "2026-07-25T17:00:00Z",
    read_only: false,
    can_edit_questions: true,
    can_add_questions: true,
    can_add_recipients: true,
    can_create_successor: false,
    owner_timezone: "UTC",
    overdue: false,
    parent_ask_id: null,
    project: { id: "project-1", name: "Atlas" },
    initiative: { id: "initiative-1", name: "Pool matching" },
    questions: [
      {
        id: "question-1",
        template_id: "open_question",
        primitive: "text",
        version: 1,
        supersedes_question_id: null,
        copied_from_question_id: null,
        ordinal: 0,
        prompt: "Which patients should match?",
        help_text: null,
        allow_comment: true,
        depends_on: null,
        response_visibility: "after_own_response",
        close_policy: "either",
        open_to: "assigned_only",
        options: [],
        critiques_overridden: [],
      },
    ],
    recipients: [
      {
        id: "recipient-1",
        actor_id: "matt-1",
        display_name: "Matt",
        email: "matt@example.com",
        created_at: "2026-07-25T17:00:00Z",
        credential_active: false,
        share_marked_sent_at: null,
        open_assignments: 0,
        recent_assignments: 0,
        recent_asks: 0,
        window_days: 7,
        workload_warning: false,
      },
    ],
    recipient_previews: [],
  };
}

export function resultsFixture() {
  return {
    id: "ask-1",
    title: "Confirm desired state",
    status: "sent",
    owner_id: "owner-1",
    sent_at: "2026-07-25T17:00:00Z",
    closed_at: null,
    deadline: null,
    elapsed_seconds: 7200,
    overdue: false,
    parent_ask_id: null,
    can_decide: true,
    questions: [
      {
        id: "question-1",
        ordinal: 0,
        prompt: "Which patients should match?",
        primitive: "text",
        version: 1,
        state: "open",
        close_policy: "either",
        open_to: "assigned_only",
        overdue: false,
        supersedes_question_id: null,
        copied_from_question_id: null,
        can_contribute_advisory: false,
        options: [],
        outcome_effect: null,
        outcome_effect_note: null,
        decision: null,
        assignments: [
          {
            id: "assignment-1",
            recipient_id: "recipient-1",
            display_name: "Matt",
            state: "responded",
            origin: "assigned",
            late: false,
            elapsed_seconds: 900,
            distinct_ip_count: 2,
            child_ask_id: null,
            delegated_to_actor_id: null,
            latest_response: {
              id: "response-1",
              version: 1,
              disposition: "answered",
              value: "Use active trial candidates.",
              comment: "Include screening status.",
              created_at: "2026-07-25T17:15:00Z",
            },
            revisions: [
              {
                id: "response-1",
                version: 1,
                disposition: "answered",
                value: "Use active trial candidates.",
                comment: "Include screening status.",
                created_at: "2026-07-25T17:15:00Z",
              },
            ],
            response_visible: true,
          },
          {
            id: "assignment-2",
            recipient_id: "recipient-2",
            display_name: "April",
            state: "pending",
            origin: "assigned",
            late: false,
            elapsed_seconds: 7200,
            distinct_ip_count: 0,
            child_ask_id: null,
            delegated_to_actor_id: null,
            latest_response: null,
            revisions: [],
            response_visible: true,
          },
        ],
      },
    ],
    stakeholders: [
      {
        recipient_id: "recipient-1",
        display_name: "Matt",
        distinct_ip_count: 2,
        questions: [
          { question_id: "question-1", assignment_id: "assignment-1" },
        ],
      },
      {
        recipient_id: "recipient-2",
        display_name: "April",
        distinct_ip_count: 0,
        questions: [
          { question_id: "question-1", assignment_id: "assignment-2" },
        ],
      },
    ],
  };
}

export function proposalResultsFixture() {
  const results = resultsFixture();
  return structuredClone({
    ...results,
    questions: [
      {
        ...results.questions[0],
        primitive: "select_one",
        prompt: "Approve the direction?",
        state: "closed",
        options: [
          { value: "approve", label: "Approve" },
          { value: "reject", label: "Reject" },
        ],
        decision: {
          id: "decision-1",
          state: "proposed",
          basis: "majority",
          value: "approve",
          statement: "Approve the direction?: Approve.",
          committed_at: null,
          shared_with_recipients_at: null,
          substantive_evidence_count: 1,
          evidence: [{ response_id: "response-1", role: "determining" }],
          advisory_disagreement: false,
          supersedes_decision_id: null,
          successor_decision_id: null,
          historical: false,
          resolution: {
            computed_winner: true,
            computed_value: "approve",
            computed_basis: "majority",
            eligible_count: 2,
            substantive_count: 2,
            quorum_met: true,
            conflict: false,
            vote_counts: { approve: 2 },
            proposal_state: "proposed",
          },
        },
      },
    ],
  });
}
