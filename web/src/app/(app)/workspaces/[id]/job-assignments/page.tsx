"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useWorkspacePage } from "@/hooks/use-workspace-page";
import { fetchWorkspaceIntegrations } from "@/lib/workspace-integrations";
import { fetchCyberIdentities } from "@/lib/workspace-cyber-identities";
import { IntegrationActionsTriggersEditor } from "@/components/job-assignments/integration-actions-triggers-editor";
import {
  buildActionsPayload,
  buildTriggersPayload,
  createJobAssignment,
  deleteJobAssignment,
  directDmRecipientsValidationError,
  fetchJobAssignments,
  fetchWorkspaceActionables,
  updateJobAssignment,
  type JobAssignment,
  type JobAssignmentActionDirectRecipient,
} from "@/lib/workspace-job-assignments";

export default function WorkspaceJobAssignmentsPage() {
  const queryClient = useQueryClient();
  const {
    workspaceId,
    token,
    orgId,
    sessionOk,
    displayUser,
    workspace,
    workspacesPending: wsPending,
    workspaceMismatch,
    workspaceReady: baseEnabled,
    selectedWorkspaceId,
  } = useWorkspacePage();

  const { data: integrations } = useQuery({
    queryKey: ["workspace-integrations", token, orgId, workspaceId],
    queryFn: () => fetchWorkspaceIntegrations(token!, orgId!, workspaceId),
    enabled: baseEnabled,
    staleTime: 15_000,
  });

  const { data: actionables, isPending: actionablesPending } = useQuery({
    queryKey: ["workspace-actionables", token, orgId, workspaceId],
    queryFn: () => fetchWorkspaceActionables(token!, orgId!, workspaceId),
    enabled: baseEnabled,
    staleTime: 15_000,
  });

  const { data: identities } = useQuery({
    queryKey: ["cyber-identities", token, orgId, workspaceId],
    queryFn: () => fetchCyberIdentities(token!, orgId!, workspaceId),
    enabled: baseEnabled,
    staleTime: 15_000,
  });

  const {
    data: jobs,
    isPending: jobsPending,
    error: jobsError,
  } = useQuery({
    queryKey: ["job-assignments", token, orgId, workspaceId],
    queryFn: () => fetchJobAssignments(token!, orgId!, workspaceId),
    enabled: baseEnabled,
    staleTime: 15_000,
  });

  const [createOpened, { open: openCreate, close: closeCreate }] = useDisclosure(false);
  const [roleName, setRoleName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [selectedIdentityId, setSelectedIdentityId] = useState<string | null>(null);
  const [selectedActionKeys, setSelectedActionKeys] = useState<string[]>([]);
  const [directDmRecipientsByKey, setDirectDmRecipientsByKey] = useState<
    Record<string, JobAssignmentActionDirectRecipient[]>
  >({});
  const [integrationEventSlugs, setIntegrationEventSlugs] = useState<string[]>([]);
  const [formError, setFormError] = useState<string | null>(null);

  const closeCreateModal = useCallback(() => {
    setIntegrationEventSlugs([]);
    setDirectDmRecipientsByKey({});
    closeCreate();
  }, [closeCreate]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["job-assignments", token, orgId, workspaceId] });
  };

  const createMutation = useMutation({
    mutationFn: () => {
      const actions = buildActionsPayload(selectedActionKeys, directDmRecipientsByKey);
      return createJobAssignment(token!, orgId!, workspaceId, {
        role_name: roleName.trim(),
        description: description.trim(),
        instructions: instructions.trim(),
        enabled: true,
        identity_id: selectedIdentityId ?? null,
        config: {
          actions,
          triggers: buildTriggersPayload(integrationEventSlugs, []),
        },
      });
    },
    onSuccess: async () => {
      setFormError(null);
      setRoleName("");
      setDescription("");
      setInstructions("");
      setSelectedIdentityId(null);
      setSelectedActionKeys([]);
      setDirectDmRecipientsByKey({});
      closeCreateModal();
      invalidate();
    },
    onError: (err: Error) => setFormError(err.message),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ row, next }: { row: JobAssignment; next: boolean }) =>
      updateJobAssignment(token!, orgId!, workspaceId, row.id, { enabled: next }),
    onSuccess: () => invalidate(),
  });

  const deleteMutation = useMutation({
    mutationFn: (row: JobAssignment) =>
      deleteJobAssignment(token!, orgId!, workspaceId, row.id),
    onSuccess: () => invalidate(),
  });

  const identityOptions = useMemo(
    () =>
      (identities ?? []).map((i) => ({
        value: i.id,
        label: `${i.display_name} (${i.type})`,
      })),
    [identities],
  );

  const createDmRecipientsError = useMemo(
    () => directDmRecipientsValidationError(selectedActionKeys, directDmRecipientsByKey),
    [selectedActionKeys, directDmRecipientsByKey],
  );

  useEffect(() => {
    if (!identities?.length || selectedIdentityId != null) return;
    queueMicrotask(() => setSelectedIdentityId(identities[0].id));
  }, [identities, selectedIdentityId]);

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

  const hasIntegration = (integrations?.length ?? 0) > 0;

  return (
    <Container size="md" py="xl" style={{ flex: 1 }}>
      <Stack gap="lg">
        <div>
          <Button component={Link} href="/workspace" variant="subtle" size="xs" mb="xs">
            ← Workspace home
          </Button>
          <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
            <div>
              <Title order={2}>Job assignments</Title>
              <Text size="sm" c="dimmed" mt={4}>
                Workspace: <strong>{workspace.name}</strong>
              </Text>
            </div>
            <Group gap="xs">
              <Button component={Link} href={`/workspaces/${workspaceId}/connect-integration`} variant="default">
                Connect account
              </Button>
              <Button
                onClick={openCreate}
                disabled={
                  !hasIntegration ||
                  (actionables?.length ?? 0) === 0 ||
                  (identities?.length ?? 0) === 0
                }
              >
                New job
              </Button>
            </Group>
          </Group>
        </div>

        {workspaceMismatch ? (
          <Alert color="yellow" title="Different workspace selected in sidebar">
            The URL points to workspace id {workspaceId}, but the sidebar has workspace{" "}
            {selectedWorkspaceId} selected.
          </Alert>
        ) : null}

        {!hasIntegration ? (
          <Alert color="blue" title="Connect an integration first">
            Job actions are built from your connected accounts (e.g. Telegram).{" "}
            <Button component={Link} href={`/workspaces/${workspaceId}/connect-integration`} variant="light" size="xs" mt="xs">
              Connect Telegram
            </Button>
          </Alert>
        ) : null}

        {hasIntegration && !actionablesPending && (actionables?.length ?? 0) === 0 ? (
          <Alert color="yellow" title="No actionables for current integrations">
            Connect a Telegram bot to unlock the &quot;Send Telegram message&quot; actionable.
          </Alert>
        ) : null}

        {(identities?.length ?? 0) === 0 ? (
          <Alert color="orange" title="Create a cyber identity first">
            Jobs require at least one identity.{" "}
            <Button component={Link} href={`/workspaces/${workspaceId}/cyber-identities`} variant="light" size="xs" mt="xs">
              Manage cyber identities
            </Button>
          </Alert>
        ) : null}

        {jobsError ? (
          <Alert color="red" title="Could not load job assignments">
            {(jobsError as Error).message}
          </Alert>
        ) : null}

        <Paper withBorder radius="md" p="lg">
          {jobsPending ? (
            <Center py="xl">
              <Loader size="sm" />
            </Center>
          ) : !jobs?.length ? (
            <Stack gap="sm">
              <Text c="dimmed" size="sm">
                No jobs yet. Create one to wire triggers and actions (runner comes later).
              </Text>
              <Button
                variant="light"
                w="fit-content"
                onClick={openCreate}
                disabled={
                  !hasIntegration ||
                  (actionables?.length ?? 0) === 0 ||
                  (identities?.length ?? 0) === 0
                }
              >
                Create first job
              </Button>
            </Stack>
          ) : (
            <Table striped highlightOnHover verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Role</Table.Th>
                  <Table.Th>Identity</Table.Th>
                  <Table.Th>Enabled</Table.Th>
                  <Table.Th>Actions</Table.Th>
                  <Table.Th>Created</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {jobs.map((row) => {
                  const acts = (row.config.actions as unknown[]) ?? [];
                  const identityLabel = row.identity_id
                    ? (identities?.find((i) => i.id === row.identity_id)?.display_name ?? row.identity_id.slice(0, 8))
                    : null;
                  return (
                    <Table.Tr key={row.id}>
                      <Table.Td>
                        <Text fw={500}>{row.role_name}</Text>
                        {row.description ? (
                          <Text size="xs" c="dimmed" lineClamp={2}>
                            {row.description}
                          </Text>
                        ) : null}
                      </Table.Td>
                      <Table.Td>
                        {identityLabel ? (
                          <Badge size="sm" variant="outline">{identityLabel}</Badge>
                        ) : (
                          <Text size="xs" c="dimmed">—</Text>
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Switch
                          checked={row.enabled}
                          onChange={(e) => {
                            const next = e.currentTarget.checked;
                            toggleMutation.mutate({ row, next });
                          }}
                          disabled={toggleMutation.isPending}
                        />
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4}>
                          {acts.slice(0, 3).map((a, i) => (
                            <Badge key={i} size="sm" variant="light">
                              {typeof a === "object" && a !== null && "actionable_slug" in a
                                ? String((a as { actionable_slug: string }).actionable_slug)
                                : "?"}
                            </Badge>
                          ))}
                          {acts.length > 3 ? (
                            <Text size="xs" c="dimmed">
                              +{acts.length - 3}
                            </Text>
                          ) : null}
                        </Group>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs">{new Date(row.created).toLocaleString()}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4} justify="flex-end">
                          <Button
                            size="xs"
                            variant="light"
                            component={Link}
                            href={`/workspaces/${workspaceId}/job-assignments/${row.id}`}
                          >
                            Open
                          </Button>
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            onClick={() => {
                              if (confirm(`Delete job "${row.role_name}"?`)) {
                                deleteMutation.mutate(row);
                              }
                            }}
                            disabled={deleteMutation.isPending}
                            aria-label="Delete"
                            title="Delete"
                          >
                            ✕
                          </ActionIcon>
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          )}
        </Paper>
      </Stack>

      <Modal opened={createOpened} onClose={closeCreateModal} title="New job assignment" centered size="lg">
        <Stack gap="sm">
          {formError ? (
            <Alert color="red" title="Could not create">
              {formError}
            </Alert>
          ) : null}
          <TextInput
            label="Role name"
            placeholder="e.g. Telegram message responder"
            value={roleName}
            onChange={(e) => {
              const value = e.currentTarget.value;
              setRoleName(value);
            }}
            data-autofocus
          />
          <TextInput
            label="Description"
            placeholder="Short summary of what this job does"
            value={description}
            onChange={(e) => {
              const value = e.currentTarget.value;
              setDescription(value);
            }}
          />
          <TextInput
            label="Instructions"
            placeholder="Detailed instructions for the agent"
            value={instructions}
            onChange={(e) => {
              const value = e.currentTarget.value;
              setInstructions(value);
            }}
          />
          <Select
            label="Cyber identity"
            placeholder="Pick the identity in charge of this job"
            data={identityOptions}
            value={selectedIdentityId}
            onChange={setSelectedIdentityId}
            searchable
            clearable={false}
            allowDeselect={false}
            description="Required — the agent runs in the context of this workspace persona."
          />
          {createDmRecipientsError ? (
            <Alert color="yellow" title="Direct DM actions">
              {createDmRecipientsError}
            </Alert>
          ) : null}
          <IntegrationActionsTriggersEditor
            actionables={actionables ?? []}
            integrations={integrations ?? []}
            actionKeys={selectedActionKeys}
            integrationEventSlugs={integrationEventSlugs}
            directDmRecipientsByKey={directDmRecipientsByKey}
            onActionKeysChange={setSelectedActionKeys}
            onIntegrationEventSlugsChange={setIntegrationEventSlugs}
            onDirectDmRecipientsByKeyChange={setDirectDmRecipientsByKey}
          />
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={closeCreateModal}>
              Cancel
            </Button>
            <Button
              loading={createMutation.isPending}
              onClick={() => createMutation.mutate()}
              disabled={
                !roleName.trim() ||
                  selectedActionKeys.length === 0 ||
                  selectedIdentityId == null ||
                  createDmRecipientsError != null
              }
            >
              Create
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Container>
  );
}
