import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { apiRequest as request } from "./apiClient";
import type { AdminAccess } from "./apiTypes";

type Actor = AdminAccess["actors"][number];
type Project = AdminAccess["projects"][number];
type Membership = AdminAccess["memberships"][number];

export function Admin() {
  const client = useQueryClient();
  const access = useQuery({ queryKey: ["admin-access"], queryFn: () => request<AdminAccess>("/api/admin/access") });
  const [email, setEmail] = useState("");
  const [projectName, setProjectName] = useState("");
  const [description, setDescription] = useState("");
  const refresh = () => client.invalidateQueries({ queryKey: ["admin-access"] });
  const invitation = useMutation({ mutationFn: () => request("/api/admin/invitations", "POST", { email }), onSuccess: async () => { setEmail(""); await refresh(); } });
  const project = useMutation({ mutationFn: () => request("/api/admin/projects", "POST", { name: projectName, description: description || null }), onSuccess: async () => { setProjectName(""); setDescription(""); await refresh(); } });

  if (access.isPending) return <AdminStatus title="Opening access control" />;
  if (access.isError) return <AdminStatus title="Administration unavailable" detail={access.error.message} />;
  const data = access.data;
  const activeActors = data.actors.filter((actor) => actor.authenticated && !actor.deactivated);

  function submitInvitation(event: FormEvent) { event.preventDefault(); invitation.mutate(); }
  function submitProject(event: FormEvent) { event.preventDefault(); project.mutate(); }

  return <div className="admin-shell">
    <header className="admin-header">
      <div><a className="wordmark" href="/">FAQ</a><p className="eyebrow">Organization controls</p><h1>Access, without ambiguity.</h1></div>
      <a className="text-button" href="/">Return to workspace</a>
    </header>
    <main className="admin-main">
      <section className="admin-section" aria-labelledby="people-title">
        <div className="admin-section-heading"><div><p className="eyebrow">01 / People</p><h2 id="people-title">Organization roster</h2></div><form className="compact-form" onSubmit={submitInvitation}><label><span>Invite by email</span><input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label><button className="primary" disabled={invitation.isPending}>{invitation.isPending ? "Inviting..." : "Invite"}</button></form></div>
        {invitation.error && <p className="form-error" role="alert">{invitation.error.message}</p>}
        {!!data.invitations.length && <div className="invitation-strip">{data.invitations.map((item) => <div key={item.id}><span><strong>{item.email}</strong><small>Expires {formatDate(item.expires_at)}</small></span><Action label="Revoke invitation" confirm={`Revoke the invitation for ${item.email}?`} action={() => request(`/api/admin/invitations/${item.id}`, "DELETE")} refresh={refresh} /></div>)}</div>}
        <div className="people-table">
          {data.actors.map((actor) => <ActorRow key={actor.id} actor={actor} activeActors={activeActors} refresh={refresh} />)}
          {!data.actors.length && <p className="empty">No identities have signed in yet.</p>}
        </div>
      </section>

      <section className="admin-section" aria-labelledby="projects-title">
        <div className="admin-section-heading"><div><p className="eyebrow">02 / Projects</p><h2 id="projects-title">Project access</h2></div><form className="compact-form project-form" onSubmit={submitProject}><label><span>Project name</span><input required maxLength={200} value={projectName} onChange={(event) => setProjectName(event.target.value)} /></label><label><span>Description</span><input value={description} onChange={(event) => setDescription(event.target.value)} /></label><button className="primary" disabled={project.isPending}>{project.isPending ? "Creating..." : "Create"}</button></form></div>
        {project.error && <p className="form-error" role="alert">{project.error.message}</p>}
        <div className="project-access-grid">{data.projects.map((item) => <ProjectAccess key={item.id} project={item} actors={activeActors} memberships={data.memberships.filter((membership) => membership.project_id === item.id)} refresh={refresh} />)}{!data.projects.length && <p className="empty">Create the first Project to begin assigning access.</p>}</div>
      </section>
    </main>
  </div>;
}

function ActorRow({ actor, activeActors, refresh }: { actor: Actor; activeActors: Actor[]; refresh: () => Promise<unknown> }) {
  const [transferTo, setTransferTo] = useState("");
  const validTransferTo = activeActors.some((item) => item.id === transferTo && item.id !== actor.id) ? transferTo : "";
  return <article className={actor.deactivated ? "person deactivated" : "person"}>
    <div><strong>{actor.display_name}</strong><small>{actor.email ?? (actor.authenticated ? "Authenticated identity" : "Respondent only")}</small></div>
    <span className="role-badge">{actor.role}</span>
    {!actor.deactivated && actor.authenticated && <>
      <Action label={actor.role === "admin" ? "Make member" : "Make admin"} confirm={`${actor.role === "admin" ? "Demote" : "Promote"} ${actor.display_name} to ${actor.role === "admin" ? "member" : "admin"}? This changes their organization authority.`} action={() => request(`/api/admin/actors/${actor.id}/role`, "PATCH", { role: actor.role === "admin" ? "member" : "admin" })} refresh={refresh} />
      <label className="transfer-select"><span>Transfer live Asks to</span><select value={validTransferTo} onChange={(event) => setTransferTo(event.target.value)}><option value="">None needed</option>{activeActors.filter((item) => item.id !== actor.id).map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>
      <Action danger label="Deactivate" confirm={`Deactivate ${actor.display_name}?`} action={() => request(`/api/admin/actors/${actor.id}${validTransferTo ? `?transfer_to=${validTransferTo}` : ""}`, "DELETE")} refresh={refresh} />
    </>}
    {actor.deactivated && <span className="muted">Deactivated</span>}
  </article>;
}

function ProjectAccess({ project, actors, memberships, refresh }: { project: Project; actors: Actor[]; memberships: Membership[]; refresh: () => Promise<unknown> }) {
  const [actorId, setActorId] = useState("");
  const [role, setRole] = useState("");
  const memberIds = new Set(memberships.map((item) => item.actor_id));
  const available = actors.filter((actor) => !memberIds.has(actor.id));
  const validActorId = available.some((actor) => actor.id === actorId) ? actorId : "";
  const grant = useMutation({ mutationFn: () => request(`/api/admin/projects/${project.id}/memberships`, "POST", { actor_id: validActorId, role: role || null }), onSuccess: async () => { setActorId(""); setRole(""); await refresh(); } });
  return <article className="project-access-card">
    <header><div><span>{project.archived ? "Archived" : "Active Project"}</span><h3>{project.name}</h3></div><Action label={project.archived ? "Reactivate" : "Archive"} confirm={project.archived ? undefined : `Archive Project ${project.name}? It will become read-only.`} action={() => request(`/api/admin/projects/${project.id}/${project.archived ? "reactivate" : "archive"}`, "POST")} refresh={refresh} /></header>
    <div className="membership-list">{memberships.map((membership) => { const actor = actors.find((item) => item.id === membership.actor_id); return <MembershipRow key={membership.actor_id} projectId={project.id} actor={actor} membership={membership} actors={actors.filter((item) => memberIds.has(item.id))} refresh={refresh} />; })}{!memberships.length && <small>No members assigned.</small>}</div>
    {!project.archived && <><form className="membership-form" onSubmit={(event) => { event.preventDefault(); grant.mutate(); }}><select aria-label={`New member for ${project.name}`} required value={validActorId} onChange={(event) => setActorId(event.target.value)}><option value="">Add a person...</option>{available.map((actor) => <option key={actor.id} value={actor.id}>{actor.display_name}</option>)}</select><input aria-label={`Project role for ${project.name}`} placeholder="Project role (optional)" maxLength={100} value={validActorId ? role : ""} onChange={(event) => setRole(event.target.value)} /><button className="primary" disabled={!validActorId || grant.isPending}>{grant.isPending ? "Granting..." : "Grant access"}</button></form>{grant.error && <p className="form-error" role="alert">{grant.error.message}</p>}</>}
  </article>;
}

function MembershipRow({ projectId, actor, membership, actors, refresh }: { projectId: string; actor?: Actor; membership: Membership; actors: Actor[]; refresh: () => Promise<unknown> }) {
  const [transferTo, setTransferTo] = useState("");
  const validTransferTo = actors.some((item) => item.id === transferTo && item.id !== membership.actor_id) ? transferTo : "";
  const actorName = actor?.display_name ?? "Unknown actor";
  const transferName = actors.find((item) => item.id === validTransferTo)?.display_name;
  return <div className="membership"><span><strong>{actorName}</strong><small>{membership.role ?? "Member"}</small></span><select aria-label={`Transfer ${actorName} Asks to`} value={validTransferTo} onChange={(event) => setTransferTo(event.target.value)}><option value="">No transfer</option>{actors.filter((item) => item.id !== membership.actor_id).map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select><Action danger label="Remove" confirm={`Remove ${actorName} from this Project${transferName ? ` and transfer their live Asks to ${transferName}` : " without transferring ownership"}?`} action={() => request(`/api/admin/projects/${projectId}/memberships/${membership.actor_id}${validTransferTo ? `?transfer_to=${validTransferTo}` : ""}`, "DELETE")} refresh={refresh} /></div>;
}

function Action({ label, action, refresh, danger = false, confirm }: { label: string; action: () => Promise<unknown>; refresh: () => Promise<unknown>; danger?: boolean; confirm?: string }) {
  const mutation = useMutation({ mutationFn: action, onSuccess: refresh });
  return <span className="action-wrap"><button className={danger ? "danger-button" : "text-button"} type="button" disabled={mutation.isPending} onClick={() => { if (!confirm || window.confirm(confirm)) mutation.mutate(); }}>{mutation.isPending ? "Working..." : label}</button>{mutation.error && <small className="form-error" role="alert">{mutation.error.message}</small>}</span>;
}

function AdminStatus({ title, detail }: { title: string; detail?: string }) { return <main className="status-page"><a className="wordmark" href="/">FAQ</a><p className="eyebrow">Organization controls</p><h1>{title}</h1>{detail && <p className="lede">{detail}</p>}</main>; }

function formatDate(value: string) { return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(value)); }
