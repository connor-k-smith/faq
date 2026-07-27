import { FormEvent, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useLocation, useSearch } from "wouter";
import { apiClient } from "./apiClient";
import type { FeedPage } from "./apiTypes";

export function ProjectFeed({ projectId }: { projectId: string }) {
  const [location, navigate] = useLocation();
  const searchString = useSearch();
  const params = new URLSearchParams(searchString);
  const [draft, setDraft] = useState({ searchString, value: params.get("q") ?? "" });
  const draftQuery = draft.searchString === searchString ? draft.value : params.get("q") ?? "";
  const filters = params.toString();
  const query = useInfiniteQuery({
    queryKey: ["project-feed", projectId, params.toString()],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => apiClient<FeedPage>(`/api/projects/${projectId}/feed?${filters}${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`, { signal }),
    getNextPageParam: (page) => page.next_cursor,
  });
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  const options = query.data?.pages[0];
  function apply(next: URLSearchParams) {
    next.delete("cursor");
    const queryString = next.toString();
    navigate(queryString ? `${location}?${queryString}` : location, { replace: true });
  }
  function search(event: FormEvent) {
    event.preventDefault();
    const next = new URLSearchParams(params);
    if (draftQuery) next.set("q", draftQuery);
    else next.delete("q");
    apply(next);
  }
  function filter(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    apply(next);
  }
  return <div className="feed-shell">
    <header className="author-topbar"><a className="wordmark" href="/">FAQ</a><nav><a href={`/p/${projectId}`}>Initiative map</a><span>/</span><strong>Decision feed</strong></nav></header>
    <main className="feed-main">
      <section className="review-heading"><div><p className="eyebrow">Project memory</p><h1>Find the decision, not the thread.</h1><p>Search Questions, options, outcomes, and Responses you are authorized to read.</p></div></section>
      <form className="feed-filters" onSubmit={search}>
        <label className="wide"><span>Search</span><input aria-label="Search project memory" value={draftQuery} onChange={(event) => setDraft({ searchString, value: event.target.value })} /></label>
        <label><span>Initiative</span><select aria-label="Filter by Initiative" value={params.get("initiative_id") ?? ""} onChange={(event) => filter("initiative_id", event.target.value)}><option value="">All Initiatives</option>{options?.initiatives.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        <label><span>Asker</span><select aria-label="Filter by asker" value={params.get("asker_id") ?? ""} onChange={(event) => filter("asker_id", event.target.value)}><option value="">All askers</option>{options?.askers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        <label><span>Status</span><select aria-label="Filter by status" value={params.get("status") ?? ""} onChange={(event) => filter("status", event.target.value)}><option value="">All statuses</option><option value="draft">Draft</option><option value="sent">Sent</option><option value="closed">Closed</option><option value="cancelled">Cancelled</option></select></label>
        <label><span>From</span><input type="date" aria-label="From date" value={params.get("date_from") ?? ""} onChange={(event) => filter("date_from", event.target.value)} /></label>
        <label><span>Through</span><input type="date" aria-label="Through date" value={params.get("date_to") ?? ""} onChange={(event) => filter("date_to", event.target.value)} /></label>
        <button className="primary">Search</button>
      </form>
      {query.isPending && <p role="status">Searching project memory...</p>}
      {query.isError && <p role="alert">{query.error.message}</p>}
      <section className="feed-results" aria-label="Project memory results">
        {items.map((item) => <article key={`${item.kind}-${item.source_id}`} className="feed-result"><div><span>{item.kind}{item.parent_ask_id ? " · follow-up Ask" : ""}{item.advisory ? " · advisory" : ""}{item.late ? " · late" : ""}{item.revision ? ` · revision ${item.revision}` : ""}{item.superseded ? " · historical · superseded" : ""}</span><time>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(item.occurred_at))}</time></div><p>{item.initiative_name} / {item.ask_title}</p><blockquote>{item.snippet}</blockquote><footer><span>{item.asker_name} · {item.ask_status}</span><a href={`/a/${item.ask_id}`}>Open Ask</a>{item.parent_ask_id && <a href={`/a/${item.parent_ask_id}`}>Prior or parent Ask</a>}{item.decision_id && <a href={`/d/${item.decision_id}.md`}>Export Markdown</a>}{item.successor_decision_id && <a href={`/d/${item.successor_decision_id}.md`}>Export current Decision</a>}</footer></article>)}
        {!query.isPending && !items.length && <p className="empty">No authorized Project history matches these filters.</p>}
      </section>
      {query.hasNextPage && <button className="text-button" onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage}>{query.isFetchingNextPage ? "Loading..." : "Load more"}</button>}
    </main>
  </div>;
}
