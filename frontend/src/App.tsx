import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Component, FormEvent, useEffect, useState, type ErrorInfo, type ReactNode } from "react";
import { Route, Switch, useLocation, useParams } from "wouter";

import { DraftEditor } from "./DraftEditor";
import { AskReview } from "./AskReview";
import { Admin } from "./Admin";
import { Login } from "./Login";
import { ProjectFeed } from "./ProjectFeed";
import { Inbox } from "./Inbox";
import { apiClient } from "./apiClient";
import type { InboxPage, Initiative, Landing, Project } from "./apiTypes";
import { OrganizationRoute, ProtectedRoutes, SessionProvider, useLogout, useSession } from "./session";

export function App() {
  return <SessionProvider><RouteBoundary><Switch>
    <Route path="/login"><Login /></Route>
    <Route path="/"><ProtectedRoutes><ProjectWorkspace /></ProtectedRoutes></Route>
    <Route path="/p/:projectId"><ProtectedRoutes><ProjectWorkspace /></ProtectedRoutes></Route>
    <Route path="/p/:projectId/i/:initiativeId"><ProtectedRoutes><ProjectWorkspace /></ProtectedRoutes></Route>
    <Route path="/p/:projectId/feed"><ProtectedRoutes><FeedRoute /></ProtectedRoutes></Route>
    <Route path="/inbox"><ProtectedRoutes><Inbox /></ProtectedRoutes></Route>
    <Route path="/a/:askId/edit"><ProtectedRoutes><DraftRoute /></ProtectedRoutes></Route>
    <Route path="/a/:askId"><ProtectedRoutes><ReviewRoute /></ProtectedRoutes></Route>
    <Route path="/organization"><ProtectedRoutes><OrganizationRoute><Admin /></OrganizationRoute></ProtectedRoutes></Route>
    <Route><NotFound /></Route>
  </Switch></RouteBoundary></SessionProvider>;
}

function DraftRoute() { return <DraftEditor askId={useParams().askId!} />; }
function ReviewRoute() { return <AskReview askId={useParams().askId!} />; }
function FeedRoute() { return <ProjectFeed projectId={useParams().projectId!} />; }

function ProjectWorkspace() {
  const queryClient = useQueryClient();
  const [, routerNavigate] = useLocation();
  const { projectId = null, initiativeId = null } = useParams();
  const route = { projectId, initiativeId };
  const session = useSession();
  const signOut = useLogout();
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Initiative["kind"]>("feature");
  const [description, setDescription] = useState("");
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => apiClient<Project[]>("/api/projects"),
  });
  const inbox = useQuery({ queryKey: ["inbox-count"], queryFn: () => apiClient<InboxPage>("/api/inbox?limit=1") });
  const landing = useQuery({
    queryKey: ["project", route.projectId],
    queryFn: () => apiClient<Landing>(`/api/projects/${route.projectId}`),
    enabled: route.projectId !== null,
  });

  useEffect(() => {
    if (route.projectId || !projects.data?.length) return;
    const remembered = window.localStorage.getItem("faq:last-project");
    const first = projects.data.find((project) => project.id === remembered) ?? projects.data[0];
    if (remembered && first.id !== remembered) window.localStorage.removeItem("faq:last-project");
    window.localStorage.setItem("faq:last-project", first.id);
    routerNavigate(`/p/${first.id}`, { replace: true });
  }, [projects.data, route.projectId, routerNavigate]);

  const createInitiative = useMutation({
    mutationFn: () =>
      apiClient<Initiative>(`/api/projects/${route.projectId}/initiatives`, { method: "POST", body: {
        name,
        kind,
        description: description || null,
      }}),
    onSuccess: async (initiative) => {
      await queryClient.invalidateQueries({ queryKey: ["project", route.projectId] });
      setName("");
      setDescription("");
      setShowCreate(false);
      navigate(route.projectId!, initiative.id);
    },
  });
  const createAsk = useMutation({
    mutationFn: () => apiClient<{ id: string }>("/api/asks", { method: "POST", body: {
      project_id: route.projectId,
      initiative_id: route.initiativeId,
      title: "Untitled Ask",
    }}),
    onSuccess: (ask) => { window.location.assign(`/a/${ask.id}/edit`); },
  });

  function navigate(projectId: string, initiativeId: string | null, replace = false) {
    const path = initiativeId ? `/p/${projectId}/i/${initiativeId}` : `/p/${projectId}`;
    window.localStorage.setItem("faq:last-project", projectId);
    routerNavigate(path, { replace });
  }

  function submitInitiative(event: FormEvent) {
    event.preventDefault();
    createInitiative.mutate();
  }

  if (projects.isPending || (route.projectId && landing.isPending)) {
    return <StatusPage label="Opening your workspace" />;
  }
  if (projects.isError) {
    return <StatusPage label="Projects unavailable" detail={projects.error.message} retry={() => projects.refetch()} />;
  }
  if (route.projectId && landing.isError) {
    return <StatusPage label="Project unavailable" detail={landing.error.message} retry={() => landing.refetch()} />;
  }
  if (!projects.data?.length) {
    return <StatusPage label="No project access yet" detail="Ask an organization admin to add you." action={session.data?.organization_role === "admin" ? <a className="primary" href="/organization">Open administration</a> : undefined} />;
  }

  const current = landing.data;
  const activeInitiatives = current?.initiatives.filter((item) => !item.archived) ?? [];
  const archivedInitiatives = current?.initiatives.filter((item) => item.archived) ?? [];
  const selected = current?.initiatives.find((item) => item.id === route.initiativeId);

  return (
    <div className="workspace">
      <aside className="rail">
        <a className="wordmark" href="/" aria-label="FAQ home">FAQ</a>
        <div className="rail-label">Project</div>
        <select
          aria-label="Project"
          value={route.projectId ?? ""}
          onChange={(event) => navigate(event.target.value, null)}
        >
          {projects.data.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}{project.archived ? " (archived)" : ""}
            </option>
          ))}
        </select>
        <nav aria-label="Project navigation">
          <a className={!route.initiativeId ? "active" : ""} href={`/p/${route.projectId}`}>
            Initiative map
          </a>
          <a className="inbox-nav" href="/inbox"><span>Inbox</span>{inbox.data?.counts && <strong aria-label={`${inbox.data.counts.total} open inbox items`}>{inbox.data.counts.total}</strong>}</a>
          <a href={`/p/${route.projectId}/feed`}>Decision feed</a>
          {session.data?.organization_role === "admin" && <a href="/organization">Administration</a>}
          <button className="text-button" type="button" onClick={() => void signOut()}>Sign out</button>
        </nav>
        <div className="rail-foot">Decisions without<br />thread archaeology.</div>
      </aside>

      <main className="project-main">
        <header className="project-header">
          <div>
            <p className="eyebrow">{selected ? `${selected.kind} initiative` : "Project memory"}</p>
            <h1>{selected?.name ?? current?.project.name}</h1>
            <p className="lede">{selected?.description ?? current?.project.description ?? "Work, questions, and outcomes in one place."}</p>
          </div>
          {current?.read_only || selected?.read_only ? (
            <span className="read-only">Archived · read only</span>
          ) : (
            <button className="primary" type="button" onClick={() => createAsk.mutate()} disabled={!route.initiativeId || createAsk.isPending} title={!route.initiativeId ? "Choose an Initiative first" : undefined}>
              {createAsk.isPending ? "Starting..." : "Start an Ask"}
            </button>
          )}
        </header>

        <section className="context-bar" aria-label="Authoring context">
          <label>
            <span>Initiative</span>
            <select
              aria-label="Initiative"
              value={route.initiativeId ?? ""}
              onChange={(event) => navigate(route.projectId!, event.target.value || null)}
            >
              <option value="">Choose where this work belongs</option>
              {activeInitiatives.map((initiative) => <option key={initiative.id} value={initiative.id}>{initiative.name}</option>)}
            </select>
          </label>
          {!current?.read_only && (
            <button className="text-button" type="button" onClick={() => setShowCreate((value) => !value)}>
              {showCreate ? "Cancel" : "+ New Initiative"}
            </button>
          )}
        </section>

        {showCreate && (
          <form className="create-panel" onSubmit={submitInitiative}>
            <div className="form-heading">
              <span>File the work</span>
              <strong>A name and shape are enough to begin.</strong>
            </div>
            <label><span>Name</span><input required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} autoFocus /></label>
            <label><span>Kind</span><select value={kind} onChange={(event) => setKind(event.target.value as Initiative["kind"])}><option value="feature">Feature</option><option value="milestone">Milestone</option><option value="workstream">Workstream</option><option value="other">Other</option></select></label>
            <label className="wide"><span>Description <i>optional</i></span><input maxLength={2000} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
            {createInitiative.error && <p className="form-error" role="alert">{createInitiative.error.message}</p>}
            <button className="primary" type="submit" disabled={createInitiative.isPending}>{createInitiative.isPending ? "Creating..." : "Create Initiative"}</button>
          </form>
        )}

        {selected ? (
          <InitiativeCard initiative={selected} projectId={route.projectId!} expanded />
        ) : (
          <>
            <div className="section-title"><h2>Active Initiatives</h2><span>{activeInitiatives.length.toString().padStart(2, "0")}</span></div>
            <section className="initiative-grid" aria-label="Active Initiatives">
              {activeInitiatives.map((initiative) => <InitiativeCard key={initiative.id} initiative={initiative} projectId={route.projectId!} />)}
              {!activeInitiatives.length && <p className="empty">No active Initiatives. Create the first subject for this Project.</p>}
            </section>
            {!!archivedInitiatives.length && <details className="archive"><summary>Archived Initiatives ({archivedInitiatives.length})</summary>{archivedInitiatives.map((initiative) => <InitiativeCard key={initiative.id} initiative={initiative} projectId={route.projectId!} />)}</details>}
          </>
        )}
      </main>
    </div>
  );
}

function InitiativeCard({ initiative, projectId, expanded = false }: { initiative: Initiative; projectId: string; expanded?: boolean }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(initiative.name);
  const [kind, setKind] = useState(initiative.kind);
  const [description, setDescription] = useState(initiative.description ?? "");
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["project", projectId] });
  const save = useMutation({
    mutationFn: () => apiClient<Initiative>(`/api/projects/${projectId}/initiatives/${initiative.id}`, { method: "PUT", body: { name, kind, description: description || null } }),
    onSuccess: async () => { setEditing(false); await refresh(); },
  });
  const archive = useMutation({
    mutationFn: () => apiClient(`/api/projects/${projectId}/initiatives/${initiative.id}/${initiative.archived ? "reactivate" : "archive"}`, { method: "POST" }),
    onSuccess: refresh,
  });
  function cancelEdit() {
    setName(initiative.name); setKind(initiative.kind); setDescription(initiative.description ?? ""); setEditing(false);
  }
  return (
    <article className={`initiative-card${expanded ? " expanded" : ""}`}>
      {editing ? <form className="initiative-edit" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
        <p className="eyebrow">Edit Initiative</p>
        <label><span>Name</span><input required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} autoFocus /></label>
        <label><span>Kind</span><select value={kind} onChange={(event) => setKind(event.target.value as Initiative["kind"])}><option value="feature">Feature</option><option value="milestone">Milestone</option><option value="workstream">Workstream</option><option value="other">Other</option></select></label>
        <label className="wide"><span>Description</span><textarea maxLength={2000} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
        {save.error && <p className="form-error" role="alert">{save.error.message}</p>}
        <div className="initiative-edit-actions"><button className="primary" disabled={save.isPending}>{save.isPending ? "Saving..." : "Save Initiative"}</button><button className="text-button" type="button" onClick={cancelEdit}>Cancel</button></div>
      </form> : <a className="card-link" href={`/p/${projectId}/i/${initiative.id}`}>
        <div className="card-meta"><span>{initiative.kind}</span><time>{formatDate(initiative.latest_activity_at)}</time></div>
        <h3>{initiative.name}</h3>
        {initiative.description && <p>{initiative.description}</p>}
      </a>}
      {!editing && <div className="pulse"><strong>{initiative.unresolved_count}</strong><span>unresolved<br />Ask{initiative.unresolved_count === 1 ? "" : "s"}</span></div>}
      {!editing && <div className="initiative-actions"><button className="text-button" type="button" disabled={initiative.read_only} onClick={() => setEditing(true)}>Edit</button><button className={initiative.archived ? "text-button" : "danger-button"} type="button" disabled={archive.isPending || (initiative.read_only && !initiative.archived)} onClick={() => (!initiative.archived && !window.confirm(`Archive ${initiative.name}?`)) || archive.mutate()}>{archive.isPending ? "Working..." : initiative.archived ? "Reactivate" : "Archive"}</button>{archive.error && <p className="form-error" role="alert">{archive.error.message}</p>}</div>}
      {!editing && <div className="card-columns">
        <div><h4>Asks</h4>{initiative.asks.slice(0, expanded ? undefined : 3).map((ask) => <a key={ask.id} href={ask.status === "draft" ? `/a/${ask.id}/edit` : `/a/${ask.id}`}><span>{ask.title}</span><em data-status={ask.status}>{ask.status}</em></a>)}{!initiative.asks.length && <small>Nothing asked yet.</small>}</div>
        <div><h4>Recent Decisions</h4>{initiative.recent_decisions.map((decision) => <a key={decision.id} href={`/a/${decision.ask_id}`}><span>{decision.statement}</span><time>{formatDate(decision.committed_at)}</time></a>)}{!initiative.recent_decisions.length && <small>No decisions recorded.</small>}</div>
      </div>}
    </article>
  );
}

function StatusPage({ label, detail, retry, action }: { label: string; detail?: string; retry?: () => unknown; action?: ReactNode }) {
  return <main className="status-page"><a className="wordmark" href="/">FAQ</a><p className="eyebrow">Project workspace</p><h1>{label}</h1>{detail && <p className="lede">{detail}</p>}{retry && <button className="primary" onClick={() => retry()}>Try again</button>}{action}</main>;
}

function NotFound() { return <StatusPage label="Page not found" detail="This route does not exist." />; }
class RouteBoundary extends Component<{ children: ReactNode }, { error?: Error }> {
  state: { error?: Error } = {};
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { void error; void info; }
  render() { return this.state.error ? <StatusPage label="Something went wrong" detail={this.state.error.message} retry={() => window.location.reload()} /> : this.props.children; }
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(value));
}
