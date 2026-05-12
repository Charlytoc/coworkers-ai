"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useWorkspacePage } from "@/hooks/use-workspace-page";
import { fetchWorkspaceIntegrations } from "@/lib/workspace-integrations";
import { fetchCyberIdentities } from "@/lib/workspace-cyber-identities";
import { IntegrationActionsTriggersEditor } from "@/components/job-assignments/integration-actions-triggers-editor";
import {
  buildActionsPayload,
  buildIdentitiesPayload,
  buildTriggersPayload,
  directDmRecipientsValidationError,
  fetchJobAssignment,
  fetchWorkspaceActionables,
  parseActionsFromConfig,
  splitJobTriggers,
  updateJobAssignment,
  type ActionableCatalogRow,
  type JobAssignment,
  type JobAssignmentActionDirectRecipient,
  type TriggerRecord,
} from "@/lib/workspace-job-assignments";
import type { CyberIdentity } from "@/lib/workspace-cyber-identities";
import type { WorkspaceIntegrationItem } from "@/lib/workspace-integrations";

type JobAssignmentDetailFormProps = {
  job: JobAssignment;
  workspaceId: number;
  jobId: string;
  token: string;
  orgId: string;
  identities: CyberIdentity[] | undefined;
  actionables: ActionableCatalogRow[] | undefined;
  integrations: WorkspaceIntegrationItem[] | undefined;
};

function JobAssignmentDetailForm({
  job,
  workspaceId,
  jobId,
  token,
  orgId,
  identities,
  actionables,
  integrations,
}: JobAssignmentDetailFormProps) {
  const queryClient = useQueryClient();
  const [roleName, setRoleName] = useState(job.role_name);
  const [description, setDescription] = useState(job.description ?? "");
  const [instructions, setInstructions] = useState(job.instructions ?? "");
  const [identityId, setIdentityId] = useState<string | null>(() => {
    const ids = (job.config.identities ?? []).map((i) => i.id);
    return ids[0] ?? null;
  });
  const [actionKeys, setActionKeys] = useState(
    () => parseActionsFromConfig(job.config.actions ?? []).actionKeys,
  );
  const [directDmRecipientsByKey, setDirectDmRecipientsByKey] = useState<
    Record<string, JobAssignmentActionDirectRecipient[]>
  >(() => parseActionsFromConfig(job.config.actions ?? []).directDmRecipientsByKey);
  const split = useMemo(
    () => splitJobTriggers(job.config.triggers as TriggerRecord[] | undefined),
    [job],
  );
  const [integrationEventSlugs, setIntegrationEventSlugs] = useState(
    () => split.integrationEventSlugs,
  );
  const otherTriggers = split.otherTriggers;
  const [formError, setFormError] = useState<string | null>(null);

  const invalidateList = () => {
    void queryClient.invalidateQueries({
      queryKey: ["job-assignments", token, orgId, workspaceId],
    });
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const identityPayload = buildIdentitiesPayload(
        identityId ? [identityId] : [],
        identities ?? [],
      );
      const actions = buildActionsPayload(actionKeys, directDmRecipientsByKey);
      return updateJobAssignment(token, orgId, workspaceId, jobId, {
        role_name: roleName.trim(),
        description: description.trim(),
        instructions: instructions.trim(),
        config: {
          identities: identityPayload,
          actions,
          triggers: buildTriggersPayload(integrationEventSlugs, otherTriggers),
        },
      });
    },
    onSuccess: async (updated: JobAssignment) => {
      setFormError(null);
      invalidateList();
      await queryClient.invalidateQueries({
        queryKey: ["job-assignment", token, orgId, workspaceId, jobId],
      });
      setRoleName(updated.role_name);
      setDescription(updated.description ?? "");
      setInstructions(updated.instructions ?? "");
    },
    onError: (err: Error) => setFormError(err.message),
  });

  const identityOptions = useMemo(
    () =>
      (identities ?? []).map((i) => ({
        value: i.id,
        label: `${i.display_name} (${i.type})`,
      })),
    [identities],
  );

  const saveDmRecipientsError = useMemo(
    () => directDmRecipientsValidationError(actionKeys, directDmRecipientsByKey),
    [actionKeys, directDmRecipientsByKey],
  );

  return (
    <Paper withBorder radius="md" p="lg">
      <Stack gap="md">
        <Text size="xs" c="dimmed" ff="monospace">
          ID: {job.id}
        </Text>
        {formError ? (
          <Alert color="red" title="Could not save">
            {formError}
          </Alert>
        ) : null}
        <TextInput
          label="Role name"
          value={roleName}
          onChange={(e) => setRoleName(e.currentTarget.value)}
        />
        <Textarea
          label="Description"
          value={description}
          onChange={(e) => setDescription(e.currentTarget.value)}
          autosize
          minRows={3}
          maxRows={16}
        />
        <Textarea
          label="Instructions"
          value={instructions}
          onChange={(e) => setInstructions(e.currentTarget.value)}
          autosize
          minRows={8}
          maxRows={24}
        />
        <Select
          label="Cyber identity"
          description="The workspace persona this job runs as."
          data={identityOptions}
          value={identityId}
          onChange={setIdentityId}
          searchable
          clearable={false}
          allowDeselect={false}
        />
        {saveDmRecipientsError ? (
          <Alert color="yellow" title="Direct DM actions">
            {saveDmRecipientsError}
          </Alert>
        ) : null}
        <IntegrationActionsTriggersEditor
          actionables={actionables ?? []}
          integrations={integrations ?? []}
          actionKeys={actionKeys}
          integrationEventSlugs={integrationEventSlugs}
          directDmRecipientsByKey={directDmRecipientsByKey}
          onActionKeysChange={setActionKeys}
          onIntegrationEventSlugsChange={setIntegrationEventSlugs}
          onDirectDmRecipientsByKeyChange={setDirectDmRecipientsByKey}
        />
        {otherTriggers.length > 0 ? (
          <Text size="xs" c="dimmed">
            This job also has {otherTriggers.length} non-integration trigger(s) (e.g. cron); they are
            kept when you save and are not editable in this form yet.
          </Text>
        ) : null}
        <Group justify="flex-end">
          <Button
            loading={saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
            disabled={
              !roleName.trim() ||
                actionKeys.length === 0 ||
                identityId == null ||
                saveDmRecipientsError != null
            }
          >
            Save changes
          </Button>
        </Group>
        <div>
          <Text size="sm" fw={600} mb="xs">
            Raw config (read-only)
          </Text>
          <Paper withBorder p="sm" radius="sm">
            <pre style={{ margin: 0, fontSize: 11, overflow: "auto", maxHeight: 240 }}>
              {JSON.stringify(job.config, null, 2)}
            </pre>
          </Paper>
        </div>
      </Stack>
    </Paper>
  );
}

export default function JobAssignmentDetailPage() {
  const queryClient = useQueryClient();
  const {
    params,
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

  const jobIdParam = params.jobId;
  const jobId =
    typeof jobIdParam === "string"
      ? jobIdParam
      : Array.isArray(jobIdParam)
        ? (jobIdParam[0] ?? "")
        : "";

  const baseEnabled = workspaceReady && Boolean(jobId);

  const { data: identities } = useQuery({
    queryKey: ["cyber-identities", token, orgId, workspaceId],
    queryFn: () => fetchCyberIdentities(token!, orgId!, workspaceId),
    enabled: baseEnabled,
    staleTime: 15_000,
  });

  const { data: actionables } = useQuery({
    queryKey: ["workspace-actionables", token, orgId, workspaceId],
    queryFn: () => fetchWorkspaceActionables(token!, orgId!, workspaceId),
    enabled: baseEnabled,
    staleTime: 15_000,
  });

  const { data: integrations } = useQuery({
    queryKey: ["workspace-integrations", token, orgId, workspaceId],
    queryFn: () => fetchWorkspaceIntegrations(token!, orgId!, workspaceId),
    enabled: baseEnabled,
    staleTime: 15_000,
  });

  const {
    data: job,
    isPending: jobPending,
    error: jobError,
  } = useQuery({
    queryKey: ["job-assignment", token, orgId, workspaceId, jobId],
    queryFn: () => fetchJobAssignment(token!, orgId!, workspaceId, jobId),
    enabled: baseEnabled,
    staleTime: 15_000,
  });

  const invalidateList = () => {
    void queryClient.invalidateQueries({
      queryKey: ["job-assignments", token, orgId, workspaceId],
    });
  };

  const toggleMutation = useMutation({
    mutationFn: (next: boolean) =>
      updateJobAssignment(token!, orgId!, workspaceId, jobId, { enabled: next }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["job-assignment", token, orgId, workspaceId, jobId],
      });
      invalidateList();
    },
  });

  if (!sessionOk || !displayUser) {
    return (
      <Center style={{ flex: 1 }}>
        <Loader size="sm" />
      </Center>
    );
  }

  if (Number.isNaN(workspaceId) || !jobId) {
    return (
      <Container size="sm" py="xl">
        <Alert color="red" title="Invalid link">
          <Button component={Link} href="/workspace" variant="light" size="xs" mt="sm">
            Workspace home
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

  if (orgId == null || !workspace) {
    return (
      <Container size="sm" py="xl">
        <Text c="dimmed" size="sm">
          Select an organization and open this link from a workspace you belong to.
        </Text>
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
          <Button
            component={Link}
            href={`/workspaces/${workspaceId}/job-assignments`}
            variant="subtle"
            size="xs"
            mb="xs"
          >
            ← Job assignments
          </Button>
          <Group justify="space-between" align="flex-start" wrap="wrap">
            <div>
              <Title order={2}>Job assignment</Title>
              <Text size="sm" c="dimmed" mt={4}>
                Workspace: <strong>{workspace.name}</strong>
              </Text>
            </div>
            {job ? (
              <Group gap="sm">
                <Button
                  size="xs"
                  variant="light"
                  component={Link}
                  href={`/chat?job=${encodeURIComponent(jobId)}&workspace=${workspaceId}`}
                  disabled={
                    !job.enabled || !(job.config.identities && job.config.identities.length > 0)
                  }
                  title={
                    !job.enabled
                      ? "Enable this job to use web chat"
                      : !(job.config.identities && job.config.identities.length > 0)
                        ? "Add a cyber identity to this job to use web chat"
                        : "Open web chat for this job"
                  }
                >
                  Web chat
                </Button>
                <Text size="sm" c="dimmed">
                  Enabled
                </Text>
                <Switch
                  checked={job.enabled}
                  onChange={(e) => toggleMutation.mutate(e.currentTarget.checked)}
                  disabled={toggleMutation.isPending}
                />
              </Group>
            ) : null}
          </Group>
        </div>

        {workspaceMismatch ? (
          <Alert color="yellow" title="Different workspace selected in sidebar">
            The URL points to workspace id {workspaceId}, but the sidebar has workspace{" "}
            {selectedWorkspaceId} selected.
          </Alert>
        ) : null}

        {!hasIntegration ? (
          <Alert color="blue" title="No integrations">
            Some actionables require a connected account.
          </Alert>
        ) : null}

        {jobError ? (
          <Alert color="red" title="Could not load job">
            {(jobError as Error).message}
          </Alert>
        ) : null}

        {jobPending ? (
          <Center py="xl">
            <Loader size="sm" />
          </Center>
        ) : job ? (
          <JobAssignmentDetailForm
            key={job.id}
            job={job}
            workspaceId={workspaceId}
            jobId={jobId}
            token={token!}
            orgId={orgId!}
            identities={identities}
            actionables={actionables}
            integrations={integrations}
          />
        ) : (
          <Alert color="gray" title="Not found">
            This job assignment does not exist or was removed.
          </Alert>
        )}
      </Stack>
    </Container>
  );
}
