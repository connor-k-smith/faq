/* eslint-disable react-refresh/only-export-components */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";
import { Redirect, useLocation, useSearch } from "wouter";

import { apiClient, ApiError } from "./apiClient";
import type { Session } from "./apiTypes";

const SessionContext = createContext<ReturnType<typeof useSessionQuery> | null>(null);

function useSessionQuery() {
  return useQuery({
    queryKey: ["session"],
    queryFn: () => apiClient<Session>("/api/auth/session", { authenticated: false }),
    retry: false,
  });
}

export function SessionProvider({ children }: { children: ReactNode }) {
  return <SessionContext.Provider value={useSessionQuery()}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}

export function ProtectedRoutes({ children }: { children: ReactNode }) {
  const session = useSession();
  const [location] = useLocation();
  const search = useSearch();
  if (session.isPending) return <main className="status-page"><p className="eyebrow">Secure workspace</p><h1>Opening your workspace</h1></main>;
  if (session.error instanceof ApiError && session.error.status === 401) {
    const returnTo = location + (search ? `?${search}` : "") + window.location.hash;
    return <Redirect replace to={`/login?returnTo=${encodeURIComponent(returnTo)}`} />;
  }
  if (session.isError) throw session.error;
  return children;
}

export function OrganizationRoute({ children }: { children: ReactNode }) {
  const session = useSession();
  return session.data?.organization_role === "admin" ? children : <Redirect replace to="/" />;
}

export function useLogout() {
  const client = useQueryClient();
  const [, navigate] = useLocation();
  return async () => {
    await apiClient("/api/auth/logout", { method: "POST" });
    client.clear();
    navigate("/login", { replace: true });
  };
}
