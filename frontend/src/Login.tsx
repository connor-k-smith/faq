import { FormEvent, useEffect, useState } from "react";
import { useLocation, useSearch } from "wouter";

import { buttonLabel, credentialFields, credentialLabel, credentialType, getIdentityToken } from "virtual:auth-provider";
import { apiClient } from "./apiClient";
import { useSession } from "./session";

export function Login() {
  const session = useSession();
  const [, navigate] = useLocation();
  const search = new URLSearchParams(useSearch());
  const [email, setEmail] = useState("");
  const [credential, setCredential] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  const requested = search.get("returnTo");
  const returnTo = requested?.startsWith("/") && !requested.startsWith("//") && !requested.startsWith("/login") ? requested : "/";
  useEffect(() => {
    if (session.isSuccess) navigate(returnTo, { replace: true });
  }, [navigate, returnTo, session.isSuccess]);
  if (session.isSuccess) return null;

  async function signIn(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      await apiClient("/api/auth/csrf", { authenticated: false });
      const idToken = await getIdentityToken(email, credential);
      await apiClient("/api/auth/exchange", {
        method: "POST",
        body: { id_token: idToken },
        authenticated: false,
        csrfCookie: "faq_login_csrf",
      });
      navigate(returnTo, { replace: true });
      window.location.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign-in failed.");
      setPending(false);
    }
  }

  return <main className="login-page"><div className="login-brand"><a className="wordmark" href="/">FAQ</a><p>Organization access</p><h1>Sign in to join the table.</h1></div><section className="login-panel"><p className="eyebrow">Secure sign-in</p><h2>Continue to FAQ</h2><form onSubmit={signIn}>{credentialFields && <><label><span>Email</span><input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label><label><span>{credentialLabel}</span><input type={credentialType} required value={credential} onChange={(event) => setCredential(event.target.value)} /></label></>}<button className="primary" disabled={pending}>{pending ? "Signing in..." : buttonLabel}</button></form>{error && <p className="form-error" role="alert">{error}</p>}</section></main>;
}
