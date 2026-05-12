"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Button,
  Center,
  Code,
  Container,
  Group,
  Loader,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useWorkspacePage } from "@/hooks/use-workspace-page";
import {
  fetchIntegrationConversations,
  fetchIntegrationTaskExecutions,
  fetchWorkspaceIntegrationDetail,
  type IntegrationConversationItem,
  type IntegrationTaskExecutionItem,
} from "@/lib/workspace-integrations";
import { approveTelegramSender } from "@/lib/telegram-integration";

const STATUS_COLOR: Record<string, string> = {
  pending: "gray",
  queued: "blue",
  running: "blue",
  waiting_approval: "yellow",
  completed: "green",
  failed: "red",
  cancelled: "gray",
};

const CONVERSATION_STATUS_COLOR: Record<string, string> = {
  active: "green",
  inactive: "gray",
  archived: "yellow",
  deleted: "red",
};

const SENDER_STATUS_COLOR: Record<string, string> = {
  pending: "yellow",
  not_required: "gray",
  approved: "green",
};

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function statusBadge(status: string) {
  return (
    <Badge color={STATUS_COLOR[status] ?? "gray"} variant="light">
      {status}
    </Badge>
  );
}

export default function IntegrationAccountDetailPage() {
  const {
    params,
    workspaceId,
    token,
    orgId,
    sessionOk,
    displayUser,
    workspaceReady,
  } = useWorkspacePage();

  const accountIdParam = params.accountId;

  const accountId =
    typeof accountIdParam === "string"
      ? accountIdParam
      : Array.isArray(accountIdParam)
        ? accountIdParam[0] ?? ""
        : "";

  const ready = workspaceReady && Boolean(accountId);

  const {
    data: account,
    isPending: accountPending,
    error: accountError,
  } = useQuery({
    queryKey: ["workspace-integration", token, orgId, workspaceId, accountId],
    queryFn: () => fetchWorkspaceIntegrationDetail(token!, orgId!, workspaceId, accountId),
    enabled: ready,
    staleTime: 15_000,
  });

  const {
    data: executions,
    isPending: execPending,
    error: execError,
  } = useQuery<IntegrationTaskExecutionItem[]>({
    queryKey: ["integration-task-executions", token, orgId, workspaceId, accountId],
    queryFn: () => fetchIntegrationTaskExecutions(token!, orgId!, workspaceId, accountId),
    enabled: ready,
    staleTime: 10_000,
  });

  const {
    data: conversations,
    isPending: convPending,
    error: convError,
  } = useQuery<IntegrationConversationItem[]>({
    queryKey: ["integration-conversations", token, orgId, workspaceId, accountId],
    queryFn: () => fetchIntegrationConversations(token!, orgId!, workspaceId, accountId),
    enabled: ready,
    staleTime: 10_000,
  });

  const queryClient = useQueryClient();

  const [approvalCode, setApprovalCode] = useState("");
  const [approveError, setApproveError] = useState<string | null>(null);
  const [approveSuccess, setApproveSuccess] = useState<string | null>(null);

  const approveMutation = useMutation({
    mutationFn: () =>
      approveTelegramSender(token!, orgId!, workspaceId, {
        integration_account_id: accountId,
        code: approvalCode.replace(/\D/g, ""),
      }),
    onSuccess: async (data) => {
      setApproveError(null);
      setApproveSuccess(
        `Sender approved (Telegram user id: ${data.approved_telegram_user_id}).`,
      );
      setApprovalCode("");
      await queryClient.invalidateQueries({
        queryKey: ["workspace-integration", token, orgId, workspaceId, accountId],
      });
    },
    onError: (err: Error) => {
      setApproveSuccess(null);
      setApproveError(err.message);
    },
  });

  const senders = useMemo(() => account?.senders ?? [], [account?.senders]);

  const configPretty = useMemo(() => {
    if (!account?.config) return "{}";
    try {
      return JSON.stringify(account.config, null, 2);
    } catch {
      return "{}";
    }
  }, [account]);

  if (!sessionOk || !displayUser) {
    return (
      <Center style={{ flex: 1 }}>
        <Loader size="sm" />
      </Center>
    );
  }

  if (Number.isNaN(workspaceId) || !accountId) {
    return (
      <Container size="sm" py="xl">
        <Alert color="red" title="Invalid URL">
          The workspace or integration id in the URL is not valid.
        </Alert>
      </Container>
    );
  }

  return (
    <Container size="lg" py="xl" style={{ flex: 1 }}>
      <Stack gap="lg">
        <div>
          <Button
            component={Link}
            href={`/workspaces/${workspaceId}/integrations`}
            variant="subtle"
            size="xs"
            mb="xs"
          >
            ← Integrations
          </Button>
          <Title order={2}>
            {account?.display_name || account?.external_account_id || "Integration account"}
          </Title>
          {account ? (
            <Group gap="xs" mt={4}>
              <Badge variant="light">{account.provider}</Badge>
              {statusBadge(account.status)}
              <Text size="xs" c="dimmed">
                External id:{" "}
                <Text span ff="monospace">
                  {account.external_account_id}
                </Text>
              </Text>
            </Group>
          ) : null}
        </div>

        {accountError ? (
          <Alert color="red" title="Could not load integration">
            {(accountError as Error).message}
          </Alert>
        ) : null}

        <Paper withBorder radius="md" p="lg">
          {accountPending ? (
            <Center py="md">
              <Loader size="sm" />
            </Center>
          ) : !account ? (
            <Text c="dimmed" size="sm">
              Integration not found.
            </Text>
          ) : (
            <Stack gap="xs">
              <Title order={4}>Account</Title>
              <Group gap="xl" wrap="wrap">
                <div>
                  <Text size="xs" c="dimmed">
                    Created
                  </Text>
                  <Text size="sm">{formatDateTime(account.created)}</Text>
                </div>
                <div>
                  <Text size="xs" c="dimmed">
                    Last synced
                  </Text>
                  <Text size="sm">{formatDateTime(account.last_synced_at)}</Text>
                </div>
                <div>
                  <Text size="xs" c="dimmed">
                    Modified
                  </Text>
                  <Text size="sm">{formatDateTime(account.modified)}</Text>
                </div>
              </Group>
              {account.last_error ? (
                <Alert color="red" title="Last error" mt="xs">
                  {account.last_error}
                </Alert>
              ) : null}
              <Text size="xs" c="dimmed" mt="xs">
                Config
              </Text>
              <Code block>{configPretty}</Code>
            </Stack>
          )}
        </Paper>

        {account?.provider === "telegram" ? (
          <Paper withBorder radius="md" p="lg">
            <Stack gap="sm">
              <Title order={4}>Approve Telegram sender</Title>
              <Text size="sm" c="dimmed">
                When someone messages your bot for the first time, they receive a 12-digit code.
                Paste it here to let them talk to this bot.
              </Text>
              {approveError ? (
                <Alert color="red" title="Could not approve" onClose={() => setApproveError(null)} withCloseButton>
                  {approveError}
                </Alert>
              ) : null}
              {approveSuccess ? (
                <Alert color="green" title="Done" onClose={() => setApproveSuccess(null)} withCloseButton>
                  {approveSuccess}
                </Alert>
              ) : null}
              <Group align="flex-end" gap="sm" wrap="wrap">
                <TextInput
                  label="12-digit approval code"
                  placeholder="000000000000"
                  value={approvalCode}
                  onChange={(e) => setApprovalCode(e.currentTarget.value)}
                  disabled={approveMutation.isPending}
                  maxLength={32}
                  style={{ flex: 1, minWidth: 260 }}
                />
                <Button
                  onClick={() => approveMutation.mutate()}
                  loading={approveMutation.isPending}
                  disabled={approvalCode.replace(/\D/g, "").length !== 12 || !ready}
                  variant="light"
                >
                  Approve sender
                </Button>
              </Group>
            </Stack>
          </Paper>
        ) : null}

        {account ? (
          <Paper withBorder radius="md" p="lg">
            <Group justify="space-between" align="center" mb="sm">
              <Title order={4}>Senders</Title>
              <Text size="xs" c="dimmed">
                External counterparts seen on this account, with their approval state and any
                context the agent has extracted.
              </Text>
            </Group>
            {senders.length === 0 ? (
              <Text c="dimmed" size="sm">
                No senders have interacted with this account yet.
              </Text>
            ) : (
              <Table striped highlightOnHover verticalSpacing="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Thread id</Table.Th>
                    <Table.Th>Handle</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th>First seen</Table.Th>
                    <Table.Th>Last seen</Table.Th>
                    <Table.Th>Extractions</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {senders.map((s) => {
                    const hasExtractions =
                      s.extractions && Object.keys(s.extractions).length > 0;
                    return (
                      <Table.Tr key={s.external_thread_id}>
                        <Table.Td>
                          <Text size="xs" ff="monospace">
                            {s.external_thread_id}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Text size="xs" ff="monospace">
                            {s.handle?.trim() ? s.handle : "—"}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Badge
                            color={SENDER_STATUS_COLOR[s.approval_status] ?? "gray"}
                            variant="light"
                          >
                            {s.approval_status}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          <Text size="xs">{formatDateTime(s.first_seen_at)}</Text>
                        </Table.Td>
                        <Table.Td>
                          <Text size="xs">{formatDateTime(s.last_seen_at)}</Text>
                        </Table.Td>
                        <Table.Td style={{ maxWidth: 360 }}>
                          {hasExtractions ? (
                            <Code block>
                              {JSON.stringify(s.extractions, null, 2)}
                            </Code>
                          ) : (
                            <Text size="xs" c="dimmed">
                              —
                            </Text>
                          )}
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            )}
          </Paper>
        ) : null}

        <Paper withBorder radius="md" p="lg">
          <Group justify="space-between" align="center" mb="sm">
            <Title order={4}>Conversations</Title>
            <Text size="xs" c="dimmed">
              Threads with external counterparts on this account.
            </Text>
          </Group>

          {convError ? (
            <Alert color="red" title="Could not load conversations">
              {(convError as Error).message}
            </Alert>
          ) : convPending ? (
            <Center py="md">
              <Loader size="sm" />
            </Center>
          ) : !conversations?.length ? (
            <Text c="dimmed" size="sm">
              No conversations yet on this account.
            </Text>
          ) : (
            <Table striped highlightOnHover verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Identity</Table.Th>
                  <Table.Th>External user</Table.Th>
                  <Table.Th>Thread</Table.Th>
                  <Table.Th>Messages</Table.Th>
                  <Table.Th>Last interaction</Table.Th>
                  <Table.Th>Created</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {conversations.map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td>
                      <Badge
                        color={CONVERSATION_STATUS_COLOR[row.status] ?? "gray"}
                        variant="light"
                      >
                        {row.status}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{row.cyber_identity_name || "—"}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" ff="monospace">
                        {row.external_user_id || "—"}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" ff="monospace">
                        {row.external_thread_id || "—"}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{row.message_count}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">{formatDateTime(row.last_interaction_at)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">{formatDateTime(row.created)}</Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Paper>

        <Paper withBorder radius="md" p="lg">
          <Group justify="space-between" align="center" mb="sm">
            <Title order={4}>Task executions</Title>
            <Text size="xs" c="dimmed">
              Runs of jobs bound to this account (via its accounts or actions).
            </Text>
          </Group>

          {execError ? (
            <Alert color="red" title="Could not load task executions">
              {(execError as Error).message}
            </Alert>
          ) : execPending ? (
            <Center py="md">
              <Loader size="sm" />
            </Center>
          ) : !executions?.length ? (
            <Text c="dimmed" size="sm">
              No task executions yet for this account.
            </Text>
          ) : (
            <Table striped highlightOnHover verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Job</Table.Th>
                  <Table.Th>Created</Table.Th>
                  <Table.Th>Scheduled</Table.Th>
                  <Table.Th>Started</Table.Th>
                  <Table.Th>Completed</Table.Th>
                  <Table.Th>ID</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {executions.map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td>
                      <Group gap={6}>
                        {statusBadge(row.status)}
                        {row.requires_approval ? (
                          <Badge color="yellow" variant="outline" size="xs">
                            approval
                          </Badge>
                        ) : null}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{row.job_role_name || "—"}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">{formatDateTime(row.created)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">{formatDateTime(row.scheduled_to)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">{formatDateTime(row.started_at)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">{formatDateTime(row.completed_at)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" ff="monospace" c="dimmed">
                        {row.id.slice(0, 8)}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Paper>
      </Stack>
    </Container>
  );
}
