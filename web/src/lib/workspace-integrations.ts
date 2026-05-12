import { apiFetch, apiReadJson } from "@/lib/api-request";

export type WorkspaceIntegrationItem = {
  id: string;
  provider: string;
  display_name: string;
  status: string;
  external_account_id: string;
  created: string;
};

export async function fetchWorkspaceIntegrations(
  token: string,
  organizationId: string,
  workspaceId: number,
): Promise<WorkspaceIntegrationItem[]> {
  const response = await apiFetch(`/workspaces/${workspaceId}/integrations/`, token, organizationId);
  return apiReadJson<WorkspaceIntegrationItem[]>(response, "Failed to load integrations");
}

export type IntegrationAccountSenderApprovalStatus =
  | "pending"
  | "not_required"
  | "approved";

export type IntegrationAccountSender = {
  external_thread_id: string;
  approval_status: IntegrationAccountSenderApprovalStatus;
  /** Display-oriented id (Telegram @username or numeric id, Instagram @username when known). */
  handle?: string | null;
  extractions: Record<string, unknown>;
  first_seen_at: string | null;
  last_seen_at: string | null;
};

export type WorkspaceIntegrationDetail = {
  id: string;
  workspace_id: number;
  provider: string;
  display_name: string;
  status: string;
  external_account_id: string;
  config: Record<string, unknown>;
  senders: IntegrationAccountSender[];
  last_synced_at: string | null;
  last_error: string;
  created: string;
  modified: string;
};

export async function fetchWorkspaceIntegrationDetail(
  token: string,
  organizationId: string,
  workspaceId: number,
  integrationAccountId: string,
): Promise<WorkspaceIntegrationDetail> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/integrations/${integrationAccountId}/`,
    token,
    organizationId,
  );
  return apiReadJson<WorkspaceIntegrationDetail>(response, "Failed to load integration");
}

export type IntegrationTaskExecutionItem = {
  id: string;
  status: string;
  requires_approval: boolean;
  job_assignment_id: string | null;
  job_role_name: string;
  scheduled_to: string | null;
  started_at: string | null;
  completed_at: string | null;
  created: string;
};

export type IntegrationConversationItem = {
  id: string;
  status: string;
  cyber_identity_id: string;
  cyber_identity_name: string;
  external_thread_id: string;
  external_user_id: string;
  message_count: number;
  last_interaction_at: string | null;
  created: string;
};

export async function fetchIntegrationConversations(
  token: string,
  organizationId: string,
  workspaceId: number,
  integrationAccountId: string,
  limit = 100,
): Promise<IntegrationConversationItem[]> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/integrations/${integrationAccountId}/conversations/?limit=${limit}`,
    token,
    organizationId,
  );
  return apiReadJson<IntegrationConversationItem[]>(response, "Failed to load conversations");
}

export async function fetchIntegrationTaskExecutions(
  token: string,
  organizationId: string,
  workspaceId: number,
  integrationAccountId: string,
  limit = 100,
): Promise<IntegrationTaskExecutionItem[]> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/integrations/${integrationAccountId}/task-executions/?limit=${limit}`,
    token,
    organizationId,
  );
  return apiReadJson<IntegrationTaskExecutionItem[]>(response, "Failed to load task executions");
}
