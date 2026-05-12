import { API_BASE_URL } from "@/lib/api-base";
import { ORGANIZATION_HEADER } from "@/lib/auth-storage";

export function apiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${p}`;
}

export function apiAuthHeaders(
  token: string,
  organizationId: string | null,
  options: { json?: boolean } = {},
): HeadersInit {
  const h: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  };
  if (organizationId != null && organizationId !== "") {
    h[ORGANIZATION_HEADER] = organizationId;
  }
  if (options.json) {
    h["Content-Type"] = "application/json";
  }
  return h;
}

export async function throwApiError(response: Response, fallback: string): Promise<never> {
  let message = fallback;
  try {
    const body = (await response.json()) as { error?: string };
    if (body?.error) message = body.error;
  } catch {
    // ignore
  }
  throw new Error(`${message} (${response.status})`);
}

export type ApiFetchInit = Omit<RequestInit, "body"> & {
  jsonBody?: unknown;
};

export async function apiFetch(
  path: string,
  token: string,
  organizationId: string | null,
  init: ApiFetchInit = {},
): Promise<Response> {
  const { jsonBody, headers: extraHeaders, ...rest } = init;
  const headers = new Headers(
    apiAuthHeaders(token, organizationId, { json: jsonBody !== undefined }),
  );
  if (extraHeaders) {
    new Headers(extraHeaders).forEach((value, key) => {
      headers.set(key, value);
    });
  }
  return fetch(apiUrl(path), {
    ...rest,
    headers,
    body: jsonBody !== undefined ? JSON.stringify(jsonBody) : undefined,
  });
}

export async function apiReadJson<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) await throwApiError(response, fallback);
  return response.json() as Promise<T>;
}

export async function apiJson<T>(
  path: string,
  token: string,
  organizationId: string | null,
  fallback: string,
  init: ApiFetchInit = {},
): Promise<T> {
  const response = await apiFetch(path, token, organizationId, init);
  return apiReadJson<T>(response, fallback);
}
