import type { components } from "@/lib/api/schema";
import { apiFetch, apiReadJson } from "@/lib/api-request";

export type WorkspaceResponse = components["schemas"]["WorkspaceResponse"];

export async function fetchWorkspaces(token: string, organizationId: string): Promise<WorkspaceResponse[]> {
  const response = await apiFetch("/workspaces/", token, organizationId);
  return apiReadJson<WorkspaceResponse[]>(response, "Failed to load workspaces");
}

export async function createWorkspace(
  token: string,
  organizationId: string,
  name: string,
): Promise<WorkspaceResponse> {
  const response = await apiFetch("/workspaces/", token, organizationId, {
    method: "POST",
    jsonBody: { name },
  });
  return apiReadJson<WorkspaceResponse>(response, "Failed to create workspace");
}

export async function patchWorkspace(
  token: string,
  organizationId: string,
  workspaceId: number,
  name: string,
): Promise<WorkspaceResponse> {
  const response = await apiFetch(`/workspaces/${workspaceId}/`, token, organizationId, {
    method: "PATCH",
    jsonBody: { name },
  });
  return apiReadJson<WorkspaceResponse>(response, "Failed to update workspace");
}
