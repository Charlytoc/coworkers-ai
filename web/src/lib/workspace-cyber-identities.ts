import { apiFetch, apiReadJson, throwApiError } from "@/lib/api-request";

export type CyberIdentityType =
  | "influencer"
  | "community_manager"
  | "analyst"
  | "personal_assistant";

export const CYBER_IDENTITY_TYPE_OPTIONS: { value: CyberIdentityType; label: string }[] = [
  { value: "influencer", label: "Influencer" },
  { value: "community_manager", label: "Community manager" },
  { value: "analyst", label: "Analyst" },
  { value: "personal_assistant", label: "Personal assistant" },
];

export const CYBER_IDENTITY_MODEL_OPTIONS: { value: string; label: string }[] = [
  { value: "gpt-5.4", label: "GPT-5.4 (gpt-5.4)" },
  { value: "gpt-5.4-mini", label: "GPT-5.4-Mini (gpt-5.4-mini)" },
  { value: "gpt-5.4-nano", label: "GPT-5.4-Nano (gpt-5.4-nano)" },
];

export type CyberIdentity = {
  id: string;
  workspace_id: number;
  type: CyberIdentityType;
  display_name: string;
  is_active: boolean;
  config: Record<string, unknown>;
  created: string;
};

export type CyberIdentityCreateInput = {
  type: CyberIdentityType;
  display_name: string;
  is_active?: boolean;
  config?: Record<string, unknown>;
};

export type CyberIdentityUpdateInput = Partial<CyberIdentityCreateInput>;

export async function fetchCyberIdentities(
  token: string,
  organizationId: string,
  workspaceId: number,
): Promise<CyberIdentity[]> {
  const response = await apiFetch(`/workspaces/${workspaceId}/cyber-identities/`, token, organizationId);
  return apiReadJson<CyberIdentity[]>(response, "Failed to load cyber identities");
}

export async function createCyberIdentity(
  token: string,
  organizationId: string,
  workspaceId: number,
  input: CyberIdentityCreateInput,
): Promise<CyberIdentity> {
  const response = await apiFetch(`/workspaces/${workspaceId}/cyber-identities/`, token, organizationId, {
    method: "POST",
    jsonBody: input,
  });
  return apiReadJson<CyberIdentity>(response, "Failed to create cyber identity");
}

export async function updateCyberIdentity(
  token: string,
  organizationId: string,
  workspaceId: number,
  cyberIdentityId: string,
  input: CyberIdentityUpdateInput,
): Promise<CyberIdentity> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/cyber-identities/${cyberIdentityId}/`,
    token,
    organizationId,
    {
      method: "PATCH",
      jsonBody: input,
    },
  );
  return apiReadJson<CyberIdentity>(response, "Failed to update cyber identity");
}

export async function deleteCyberIdentity(
  token: string,
  organizationId: string,
  workspaceId: number,
  cyberIdentityId: string,
): Promise<void> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/cyber-identities/${cyberIdentityId}/`,
    token,
    organizationId,
    {
      method: "DELETE",
    },
  );
  if (!response.ok && response.status !== 204) {
    await throwApiError(response, "Failed to delete cyber identity");
  }
}
