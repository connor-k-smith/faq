import { useInfiniteQuery } from "@tanstack/react-query";
import { apiClient } from "./apiClient";
import type { InboxPage } from "./apiTypes";

type InboxItem = InboxPage["items"][number];

const sections = [
  ["proposed_decision", "Decisions to review", "A deterministic proposal is ready for your judgment."],
  ["outcome_effect", "Outcome effect needed", "The Decision is committed; record what changed to complete it."],
  ["collecting", "Still collecting", "Sent Questions remain open for responses or owner judgment."],
] as const;

export function Inbox() {
  const inbox = useInfiniteQuery({
    queryKey: ["inbox"],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => apiClient<InboxPage>(`/api/inbox?limit=25${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`, { signal }),
    getNextPageParam: (page) => page.next_cursor,
  });
  if (inbox.isPending) return <Status text="Opening your inbox" />;
  if (inbox.isError) return <Status text="Inbox unavailable" detail={inbox.error.message} />;
  const items = inbox.data.pages.flatMap((page) => page.items);
  const counts = inbox.data.pages[0].counts;
  return <div className="inbox-shell">
    <header className="author-topbar"><a className="wordmark" href="/">FAQ</a><nav><a href="/">Projects</a><span>/</span><strong>Inbox</strong></nav><span className="draft-state">{counts.total} open</span></header>
    <main className="inbox-main">
      <header className="inbox-heading"><div><p className="eyebrow">Owned by you</p><h1>Inbox</h1></div><p>Decide what is ready.<br />Keep an eye on what is not.</p></header>
      {sections.map(([kind, title, description]) => {
        const sectionItems = items.filter((item) => item.kind === kind);
        return <section className="inbox-section" key={kind} aria-labelledby={`inbox-${kind}`}>
          <header><div><h2 id={`inbox-${kind}`}>{title}</h2><p>{description}</p></div><strong>{counts[kind]}</strong></header>
          <div className="inbox-list">{sectionItems.map((item) => <InboxCard key={`${item.kind}-${item.question_id}`} item={item} />)}{counts[kind] === 0 && <p className="inbox-empty">Nothing needs attention here.</p>}{counts[kind] > sectionItems.length && <p className="inbox-empty">{counts[kind] - sectionItems.length} more in this section. Load more below.</p>}</div>
        </section>;
      })}
      {inbox.hasNextPage && <button className="primary inbox-more" onClick={() => inbox.fetchNextPage()} disabled={inbox.isFetchingNextPage}>{inbox.isFetchingNextPage ? "Loading..." : "Load more"}</button>}
    </main>
  </div>;
}

function InboxCard({ item }: { item: InboxItem }) {
  return <a className="inbox-card" href={`/a/${item.ask_id}#question-${item.question_id}`}>
    <div className="card-meta"><span>{item.project_name} / {item.initiative_name}</span><em>{item.ask_status} / {item.question_status}</em></div>
    <h3>{item.question_prompt}</h3><p>{item.ask_title} · Question {item.question_ordinal + 1}</p>
    <dl><div><dt>Basis</dt><dd>{item.decision_basis?.replaceAll("_", " ") ?? "Responses still collecting"}</dd></div><div><dt>Deadline</dt><dd className={item.overdue ? "overdue" : ""}>{item.deadline ? `${item.overdue ? "Overdue · " : ""}${formatDate(item.deadline)}` : "No deadline"}</dd></div><div><dt>Close policy</dt><dd>{policy(item.close_policy)}</dd></div></dl>
  </a>;
}

function policy(value: string) {
  if (value === "all_responded") return "When everyone responds";
  if (value === "deadline") return "At the deadline";
  return "Everyone responds or deadline";
}
function formatDate(value: string) { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
function Status({ text, detail }: { text: string; detail?: string }) { return <main className="status-page"><a className="wordmark" href="/">FAQ</a><p className="eyebrow">Owner inbox</p><h1>{text}</h1>{detail && <p className="lede">{detail}</p>}</main>; }
