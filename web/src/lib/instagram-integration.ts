import { apiFetch, apiReadJson, throwApiError } from "@/lib/api-request";

export type InstagramOAuthUrlResponse = {
  oauth_url: string;
};

export type InstagramConnectedAccount = {
  integration_account_id: string;
  display_name: string;
  ig_username: string;
};

/**
 * Step 1 of the OAuth flow.
 * Returns the Meta authorization URL. Redirect the user (or open a popup) to this URL.
 */
export async function getInstagramOAuthUrl(
  token: string,
  organizationId: string,
  workspaceId: number,
  body: { cyber_identity_id: string; use_case: string },
): Promise<InstagramOAuthUrlResponse> {
  const response = await apiFetch(
    `/integrations/instagram/workspaces/${workspaceId}/instagram/oauth-url`,
    token,
    organizationId,
    {
      method: "POST",
      jsonBody: body,
    },
  );
  return apiReadJson<InstagramOAuthUrlResponse>(response, "Failed to get Instagram OAuth URL");
}

/**
 * Delete a connected Instagram integration account.
 */
export async function disconnectInstagramIntegration(
  token: string,
  organizationId: string,
  workspaceId: number,
  integrationAccountId: string,
): Promise<void> {
  const response = await apiFetch(
    `/integrations/instagram/workspaces/${workspaceId}/instagram/${integrationAccountId}`,
    token,
    organizationId,
    {
      method: "DELETE",
    },
  );
  if (!response.ok && response.status !== 204) {
    await throwApiError(response, "Failed to disconnect Instagram");
  }
}
