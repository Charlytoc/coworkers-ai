"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Paper,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useWorkspacePage } from "@/hooks/use-workspace-page";
import { disconnectTelegramIntegration } from "@/lib/telegram-integration";
import { disconnectInstagramIntegration } from "@/lib/instagram-integration";
import { fetchWorkspaceIntegrations } from "@/lib/workspace-integrations";

export default function WorkspaceIntegrationsPage() {
  const {
    router,
    workspaceId,
    token,
    orgId,
    sessionOk,
    displayUser,
    workspace,
    workspacesPending: wsPending,
    workspaceMismatch,
    workspaceReady,
    selectedWorkspaceId,
  } = useWorkspacePage();
  const queryClient = useQueryClient();

  const searchParams = useSearchParams();
  const [disconnectError, setDisconnectError] = useState<string | null>(null);
  const [igSuccess, setIgSuccess] = useState(false);
  const [igConnectError, setIgConnectError] = useState<string | null>(null);

  useEffect(() => {
    if (Number.isNaN(workspaceId)) return;
    const connected = searchParams.get("instagram_connected") === "true";
    const err = searchParams.get("instagram_error");
    if (!connected && err == null) return;

    if (connected) setIgSuccess(true);
    if (err != null && err !== "") setIgConnectError(err);

    const next = new URLSearchParams(searchParams.toString());
    next.delete("instagram_connected");
    next.delete("instagram_error");
    const base = `/workspaces/${workspaceId}/integrations`;
    router.replace(next.toString() ? `${base}?${next.toString()}` : base, { scroll: false });
  }, [workspaceId, router, searchParams]);

  const {
    data: integrations,
    isPending: intPending,
    error: intError,
  } = useQuery({
    queryKey: ["workspace-integrations", token, orgId, workspaceId],
    queryFn: () => fetchWorkspaceIntegrations(token!, orgId!, workspaceId),
    enabled: workspaceReady,
    staleTime: 15_000,
  });

  const invalidateIntegrations = async () => {
    await queryClient.invalidateQueries({ queryKey: ["workspace-integrations", token, orgId, workspaceId] });
    await queryClient.invalidateQueries({ queryKey: ["workspace-actionables", token, orgId, workspaceId] });
    await queryClient.invalidateQueries({ queryKey: ["job-assignments", token, orgId, workspaceId] });
  };

  const disconnectMutation = useMutation({
    mutationFn: (integrationAccountId: string) =>
      disconnectTelegramIntegration(token!, orgId!, workspaceId, integrationAccountId),
    onSuccess: async () => { setDisconnectError(null); await invalidateIntegrations(); },
    onError: (err: Error) => { setDisconnectError(err.message); },
  });

  const disconnectIgMutation = useMutation({
    mutationFn: (integrationAccountId: string) =>
      disconnectInstagramIntegration(token!, orgId!, workspaceId, integrationAccountId),
    onSuccess: async () => { setDisconnectError(null); await invalidateIntegrations(); },
    onError: (err: Error) => { setDisconnectError(err.message); },
  });

  if (!sessionOk || !displayUser) {
    return (
      <Center style={{ flex: 1 }}>
        <Loader size="sm" />
      </Center>
    );
  }

  if (Number.isNaN(workspaceId)) {
    return (
      <Container size="sm" py="xl">
        <Alert color="red" title="Invalid workspace">
          The workspace id in the URL is not valid.{" "}
          <Button component={Link} href="/workspace" variant="light" size="xs" mt="sm">
            Back to workspace
          </Button>
        </Alert>
      </Container>
    );
  }

  if (orgId != null && wsPending) {
    return (
      <Center style={{ flex: 1 }}>
        <Loader size="sm" />
      </Center>
    );
  }

  if (orgId == null) {
    return (
      <Container size="sm" py="xl">
        <Text c="dimmed" size="sm">
          Select an organization in the header first.
        </Text>
        <Button component={Link} href="/workspace" variant="light" mt="md">
          Workspace home
        </Button>
      </Container>
    );
  }

  if (!workspace) {
    return (
      <Container size="sm" py="xl">
        <Alert color="yellow" title="Workspace not found">
          This workspace is not in your list for the current organization, or the id does not match.
        </Alert>
        <Button component={Link} href="/workspace" variant="light" mt="md">
          Workspace home
        </Button>
      </Container>
    );
  }

  return (
    <Container size="md" py="xl" style={{ flex: 1 }}>
      <Stack gap="lg">
        <div>
          <Button component={Link} href="/workspace" variant="subtle" size="xs" mb="xs">
            ← Workspace home
          </Button>
          <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
            <div>
              <Title order={2}>Integrations</Title>
              <Text size="sm" c="dimmed" mt={4}>
                Workspace: <strong>{workspace.name}</strong>
              </Text>
            </div>
            <Button component={Link} href={`/workspaces/${workspaceId}/connect-integration`}>
              Add integration
            </Button>
          </Group>
        </div>

        {workspaceMismatch ? (
          <Alert color="yellow" title="Different workspace selected in sidebar">
            The URL points to workspace id {workspaceId}, but the sidebar has workspace {selectedWorkspaceId}{" "}
            selected.
          </Alert>
        ) : null}

        {igSuccess ? (
          <Alert color="green" title="Instagram connected" onClose={() => setIgSuccess(false)} withCloseButton>
            Your Instagram Business account was connected successfully.
          </Alert>
        ) : null}

        {igConnectError ? (
          <Alert color="red" title="Instagram connection failed" onClose={() => setIgConnectError(null)} withCloseButton>
            {igConnectError}
          </Alert>
        ) : null}

        {intError ? (
          <Alert color="red" title="Could not load integrations">
            {(intError as Error).message}
          </Alert>
        ) : null}

        {disconnectError ? (
          <Alert color="red" title="Could not disconnect" onClose={() => setDisconnectError(null)} withCloseButton>
            {disconnectError}
          </Alert>
        ) : null}

        <Paper withBorder radius="md" p="lg">
          {intPending ? (
            <Center py="xl">
              <Loader size="sm" />
            </Center>
          ) : !integrations?.length ? (
            <Stack gap="sm">
              <Text c="dimmed" size="sm">
                No integrations yet. Connect Telegram or Instagram to receive messages and run tasks.
              </Text>
              <Button component={Link} href={`/workspaces/${workspaceId}/connect-integration`} variant="light" w="fit-content">
                Add integration
              </Button>
            </Stack>
          ) : (
            <Table striped highlightOnHover verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Provider</Table.Th>
                  <Table.Th>Display name</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>External id</Table.Th>
                  <Table.Th>Created</Table.Th>
                  <Table.Th style={{ width: 200 }}>Actions</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {integrations.map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td>{row.provider}</Table.Td>
                    <Table.Td>{row.display_name || "—"}</Table.Td>
                    <Table.Td>{row.status}</Table.Td>
                    <Table.Td>
                      <Text size="xs" ff="monospace">
                        {row.external_account_id}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">{new Date(row.created).toLocaleString()}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        <Button
                          size="xs"
                          variant="subtle"
                          component={Link}
                          href={`/workspaces/${workspaceId}/integrations/${row.id}`}
                        >
                          View
                        </Button>
                        {row.provider === "telegram" ? (
                          <Button
                            size="xs"
                            variant="subtle"
                            color="red"
                            loading={disconnectMutation.isPending}
                            disabled={!token || orgId == null}
                            onClick={() => {
                              if (confirm(`Disconnect ${row.display_name || "this Telegram bot"}? The bot will stop receiving events here.`)) {
                                setDisconnectError(null);
                                disconnectMutation.mutate(row.id);
                              }
                            }}
                          >
                            Disconnect
                          </Button>
                        ) : row.provider === "instagram" ? (
                          <Button
                            size="xs"
                            variant="subtle"
                            color="red"
                            loading={disconnectIgMutation.isPending}
                            disabled={!token || orgId == null}
                            onClick={() => {
                              if (confirm(`Disconnect ${row.display_name || "this Instagram account"}? It will stop receiving DMs here.`)) {
                                setDisconnectError(null);
                                disconnectIgMutation.mutate(row.id);
                              }
                            }}
                          >
                            Disconnect
                          </Button>
                        ) : null}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Paper>

        {/* Approve-sender flow now lives in the integration details page (/integrations/[accountId]). */}
      </Stack>
    </Container>
  );
}
