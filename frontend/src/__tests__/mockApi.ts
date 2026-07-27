import { vi } from "vitest";

type ApiHandler = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Response | Promise<Response>;

export function mockApi(handler: ApiHandler) {
  const fetch = vi.fn(handler);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

export function jsonResponse(value: unknown, init?: ResponseInit) {
  return Response.json(value, init);
}
