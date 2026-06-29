import { apiFetch, apiReadJson, throwApiError } from "@/lib/api-request";

export type InstagramAuthMethod = "instagram_login" | "facebook_login";

export type InstagramOAuthUrlResponse = {
  oauth_url: string;
};

export type InstagramConnectedAccount = {
  integration_account_id: string;
  display_name: string;
  ig_username: string;
};

export type FacebookPageOption = {
  page_id: string;
  page_name: string;
  ig_user_id: string;
  ig_username: string;
  display_label: string;
};

export type FacebookPagesPendingResponse = {
  workspace_id: number;
  pages: FacebookPageOption[];
};

export type FacebookPageCompleteResponse = {
  integration_account_id: string;
  display_name: string;
};

/**
 * Step 1 of the OAuth flow.
 * Returns the Meta authorization URL. Redirect the user (or open a popup) to this URL.
 */
export async function getInstagramOAuthUrl(
  token: string,
  organizationId: string,
  workspaceId: number,
  body: { cyber_identity_id: string; use_case: string; auth_method?: InstagramAuthMethod },
): Promise<InstagramOAuthUrlResponse> {
  const response = await apiFetch(
    `/integrations/instagram/workspaces/${workspaceId}/instagram/oauth-url`,
    token,
    organizationId,
    {
      method: "POST",
      jsonBody: {
        ...body,
        auth_method: body.auth_method ?? "instagram_login",
      },
    },
  );
  return apiReadJson<InstagramOAuthUrlResponse>(response, "Failed to get Instagram OAuth URL");
}

export async function fetchFacebookPagesPending(
  token: string,
  organizationId: string,
  workspaceId: number,
  pending: string,
): Promise<FacebookPagesPendingResponse> {
  const response = await apiFetch(
    `/integrations/instagram/workspaces/${workspaceId}/instagram/facebook-pages?pending=${encodeURIComponent(pending)}`,
    token,
    organizationId,
  );
  return apiReadJson<FacebookPagesPendingResponse>(response, "Failed to load Facebook Pages");
}

export async function completeFacebookPageSelection(
  token: string,
  organizationId: string,
  workspaceId: number,
  body: { pending: string; page_id: string },
): Promise<FacebookPageCompleteResponse> {
  const response = await apiFetch(
    `/integrations/instagram/workspaces/${workspaceId}/instagram/facebook-pages/complete`,
    token,
    organizationId,
    {
      method: "POST",
      jsonBody: body,
    },
  );
  return apiReadJson<FacebookPageCompleteResponse>(response, "Failed to complete Facebook Page selection");
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
