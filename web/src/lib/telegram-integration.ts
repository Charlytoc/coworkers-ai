import { apiFetch, apiReadJson, throwApiError } from "@/lib/api-request";

export type TelegramConnectResponse = {
  integration_account_id: string;
  display_name: string;
};

export async function connectTelegramBot(
  token: string,
  organizationId: string,
  workspaceId: number,
  body: { bot_token: string; display_name?: string | null },
): Promise<TelegramConnectResponse> {
  const response = await apiFetch(
    `/integrations/telegram/workspaces/${workspaceId}/telegram/connect`,
    token,
    organizationId,
    {
      method: "POST",
      jsonBody: {
        bot_token: body.bot_token,
        display_name: body.display_name ?? null,
      },
    },
  );
  return apiReadJson<TelegramConnectResponse>(response, "Failed to connect Telegram");
}

export type TelegramApproveResponse = {
  approved_telegram_user_id: string;
};

export async function approveTelegramSender(
  token: string,
  organizationId: string,
  workspaceId: number,
  body: { integration_account_id: string; code: string },
): Promise<TelegramApproveResponse> {
  const response = await apiFetch(
    `/integrations/telegram/workspaces/${workspaceId}/telegram/approve-sender`,
    token,
    organizationId,
    {
      method: "POST",
      jsonBody: {
        integration_account_id: body.integration_account_id,
        code: body.code,
      },
    },
  );
  return apiReadJson<TelegramApproveResponse>(response, "Failed to approve sender");
}

export async function disconnectTelegramIntegration(
  token: string,
  organizationId: string,
  workspaceId: number,
  integrationAccountId: string,
): Promise<void> {
  const response = await apiFetch(
    `/integrations/telegram/workspaces/${workspaceId}/telegram/${integrationAccountId}`,
    token,
    organizationId,
    {
      method: "DELETE",
    },
  );
  if (!response.ok && response.status !== 204) {
    await throwApiError(response, "Failed to disconnect Telegram");
  }
}
