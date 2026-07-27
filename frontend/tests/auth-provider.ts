export const credentialFields = true;
export const credentialLabel = "Display name";
export const credentialType = "text";
export const buttonLabel = "Continue with test identity";

export async function getIdentityToken(email = "", displayName = ""): Promise<string> {
  return `playwright:${email}:${displayName}`;
}
