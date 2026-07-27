import { getApp, getApps, initializeApp } from "firebase/app";
import { getAuth, signInWithEmailAndPassword } from "firebase/auth";
import { apiClient } from "./apiClient";
import type { AuthConfig } from "./apiTypes";

export const credentialFields = true;
export const credentialLabel = "Password";
export const credentialType = "password";
export const buttonLabel = "Sign in";

export async function getIdentityToken(email = "", password = ""): Promise<string> {
  const config = await apiClient<AuthConfig>("/api/auth/config", { authenticated: false });
  if (config.provider !== "password") throw new Error("The configured sign-in provider is unsupported.");
  const app = getApps().length > 0 ? getApp() : initializeApp({
    apiKey: config.firebase.api_key,
    authDomain: config.firebase.auth_domain,
    projectId: config.firebase.project_id,
    appId: config.firebase.app_id,
  });
  const result = await signInWithEmailAndPassword(getAuth(app), email, password);
  return result.user.getIdToken();
}
