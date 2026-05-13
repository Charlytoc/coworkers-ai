"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Container,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useWorkspacePage } from "@/hooks/use-workspace-page";
import { fetchCyberIdentities } from "@/lib/workspace-cyber-identities";
import { fetchWorkspaceIntegrations } from "@/lib/workspace-integrations";
import { fetchJobAssignments } from "@/lib/workspace-job-assignments";
import {
  ARTIFACT_KIND_OPTIONS,
  artifactPreviewImageUrl,
  artifactTextBody,
  artifactTitle,
  deleteWorkspaceArtifact,
  fetchWorkspaceArtifacts,
  formatArtifactBytes,
  isHtmlTextArtifact,
  type ArtifactKind,
  type WorkspaceArtifact,
} from "@/lib/workspace-artifacts";

const ARTIFACT_CARD_PREVIEW_PX = 280;

export default function WorkspaceArtifactsPage() {
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

  const [identityId, setIdentityId] = useState<string | null>(null);
  const [jobAssignmentId, setJobAssignmentId] = useState<string | null>(null);
  const [integrationAccountId, setIntegrationAccountId] = useState<string | null>(null);
  const [kind, setKind] = useState<ArtifactKind | null>(null);
  const [artifactToDelete, setArtifactToDelete] = useState<WorkspaceArtifact | null>(null);

  const { data: identities } = useQuery({
    queryKey: ["cyber-identities", token, orgId, workspaceId],
    queryFn: () => fetchCyberIdentities(token!, orgId!, workspaceId),
    enabled: baseEnabled,
    staleTime: 15_000,
  });

  const { data: jobs } = useQuery({
    queryKey: ["job-assignments", token, orgId, workspaceId],
    queryFn: () => fetchJobAssignments(token!, orgId!, workspaceId),
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
    data: artifacts,
    isPending: artifactsPending,
    error: artifactsError,
  } = useQuery({
    queryKey: [
      "workspace-artifacts",
      token,
      orgId,
      workspaceId,
      identityId,
      jobAssignmentId,
      integrationAccountId,
      kind,
    ],
    queryFn: () =>
      fetchWorkspaceArtifacts(token!, orgId!, workspaceId, {
        identityId,
        jobAssignmentId,
        integrationAccountId,
        kind,
        limit: 200,
      }),
    enabled: baseEnabled,
    staleTime: 10_000,
  });

  const deleteMutation = useMutation({
    mutationFn: async (row: WorkspaceArtifact) => {
      if (!token || orgId == null) throw new Error("Not signed in.");
      await deleteWorkspaceArtifact(token, orgId, workspaceId, row.id);
    },
    onSuccess: () => {
      setArtifactToDelete(null);
      void queryClient.invalidateQueries({
        queryKey: [
          "workspace-artifacts",
          token,
          orgId,
          workspaceId,
          identityId,
          jobAssignmentId,
          integrationAccountId,
          kind,
        ],
      });
      void queryClient.invalidateQueries({ queryKey: ["workspace-artifact", token, orgId, workspaceId] });
    },
  });

  const identityOptions = useMemo(
    () =>
      (identities ?? []).map((row) => ({
        value: row.id,
        label: `${row.display_name} (${row.type})`,
      })),
    [identities],
  );

  const jobOptions = useMemo(
    () =>
      (jobs ?? []).map((row) => ({
        value: row.id,
        label: row.role_name,
      })),
    [jobs],
  );

  const integrationOptions = useMemo(
    () =>
      (integrations ?? []).map((row) => ({
        value: row.id,
        label: `${row.display_name || row.external_account_id} (${row.provider})`,
      })),
    [integrations],
  );

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
    <Container size="lg" py="xl" style={{ flex: 1 }}>
      <Stack gap="lg">
        <div>
          <Button component={Link} href="/workspace" variant="subtle" size="xs" mb="xs">
            ← Workspace home
          </Button>
          <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
            <div>
              <Title order={2}>Artifacts</Title>
              <Text size="sm" c="dimmed" mt={4}>
                Workspace: <strong>{workspace.name}</strong>
              </Text>
            </div>
            <Button
              component={Link}
              href={`/workspaces/${workspaceId}/job-assignments`}
              variant="default"
            >
              Manage jobs
            </Button>
          </Group>
        </div>

        {workspaceMismatch ? (
          <Alert color="yellow" title="Different workspace selected in sidebar">
            The URL points to workspace id {workspaceId}, but the sidebar has workspace{" "}
            {selectedWorkspaceId} selected.
          </Alert>
        ) : null}

        <Paper withBorder radius="md" p="md">
          <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }} spacing="sm">
            <Select
              label="Identity"
              placeholder="All identities"
              data={identityOptions}
              value={identityId}
              onChange={setIdentityId}
              searchable
              clearable
            />
            <Select
              label="Job assignment"
              placeholder="All jobs"
              data={jobOptions}
              value={jobAssignmentId}
              onChange={setJobAssignmentId}
              searchable
              clearable
            />
            <Select
              label="Integration"
              placeholder="All integrations"
              data={integrationOptions}
              value={integrationAccountId}
              onChange={setIntegrationAccountId}
              searchable
              clearable
            />
            <Select
              label="Kind"
              placeholder="All kinds"
              data={ARTIFACT_KIND_OPTIONS}
              value={kind}
              onChange={(value) => setKind(value as ArtifactKind | null)}
              clearable
            />
          </SimpleGrid>
          {identityId || jobAssignmentId || integrationAccountId || kind ? (
            <Button
              variant="subtle"
              size="xs"
              mt="sm"
              onClick={() => {
                setIdentityId(null);
                setJobAssignmentId(null);
                setIntegrationAccountId(null);
                setKind(null);
              }}
            >
              Clear filters
            </Button>
          ) : null}
        </Paper>

        {artifactsError ? (
          <Alert color="red" title="Could not load artifacts">
            {(artifactsError as Error).message}
          </Alert>
        ) : null}

        {artifactsPending ? (
          <Center py="xl">
            <Loader size="sm" />
          </Center>
        ) : !artifacts?.length ? (
          <Paper withBorder radius="md" p="lg">
            <Stack gap="sm">
              <Text c="dimmed" size="sm">
                No artifacts match these filters yet.
              </Text>
              <Button
                component={Link}
                href={`/workspaces/${workspaceId}/job-assignments`}
                variant="light"
                w="fit-content"
              >
                Review artifact-producing jobs
              </Button>
            </Stack>
          </Paper>
        ) : (
          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
            {artifacts.map((row) => {
              const preview = artifactTextBody(row);
              const previewImageUrl = artifactPreviewImageUrl(row);
              const mediaMeta = row.media
                ? [row.media.mime_type, formatArtifactBytes(row.media.byte_size)].filter(Boolean).join(" · ")
                : "";
              const showHtmlPreview = isHtmlTextArtifact(row) && preview;
              const hasInlinePreview = Boolean(preview || previewImageUrl);
              return (
                <Card key={row.id} withBorder radius="md" p="lg">
                  <Stack gap="sm">
                    <Group justify="space-between" align="flex-start" gap="xs" wrap="nowrap">
                      <div style={{ minWidth: 0 }}>
                        <Badge variant="light" mb={4}>
                          {row.kind}
                        </Badge>
                        <Title order={4}>{artifactTitle(row)}</Title>
                        <Text size="xs" c="dimmed">
                          {new Date(row.created).toLocaleString()}
                        </Text>
                      </div>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        aria-label="Delete artifact"
                        title="Delete"
                        onClick={() => setArtifactToDelete(row)}
                        disabled={deleteMutation.isPending}
                      >
                        ✕
                      </ActionIcon>
                    </Group>

                    {hasInlinePreview ? (
                      <Paper withBorder radius="sm" p="sm" bg="var(--mantine-color-gray-light)">
                        <Stack gap="xs">
                          {previewImageUrl ? (
                            <Box
                              h={ARTIFACT_CARD_PREVIEW_PX}
                              w="100%"
                              style={{
                                overflow: "hidden",
                                borderRadius: 8,
                                border: "1px solid var(--mantine-color-default-border)",
                                background: "var(--mantine-color-body)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                              }}
                            >
                              <Box
                                component="img"
                                src={previewImageUrl}
                                alt={artifactTitle(row)}
                                style={{
                                  display: "block",
                                  width: "100%",
                                  height: "100%",
                                  objectFit: "contain",
                                }}
                              />
                            </Box>
                          ) : null}
                          {preview ? (
                            previewImageUrl ? (
                              <Box
                                mah={200}
                                p="sm"
                                style={{
                                  overflow: "auto",
                                  borderRadius: 8,
                                  border: "1px solid var(--mantine-color-default-border)",
                                  background: "var(--mantine-color-gray-light)",
                                }}
                              >
                                <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                                  {preview}
                                </Text>
                              </Box>
                            ) : (
                              <Box
                                h={ARTIFACT_CARD_PREVIEW_PX}
                                w="100%"
                                style={{
                                  overflow: "hidden",
                                  borderRadius: 8,
                                  border: "1px solid var(--mantine-color-default-border)",
                                  background: "var(--mantine-color-body)",
                                }}
                              >
                                {showHtmlPreview ? (
                                  <Box
                                    component="iframe"
                                    srcDoc={preview}
                                    sandbox=""
                                    title={artifactTitle(row)}
                                    style={{
                                      display: "block",
                                      width: "100%",
                                      height: "100%",
                                      border: 0,
                                      background: "white",
                                    }}
                                  />
                                ) : (
                                  <Box
                                    h="100%"
                                    p="sm"
                                    style={{
                                      overflow: "auto",
                                      background: "var(--mantine-color-gray-light)",
                                    }}
                                  >
                                    <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                                      {preview}
                                    </Text>
                                  </Box>
                                )}
                              </Box>
                            )
                          ) : null}
                          <Button
                            component={Link}
                            href={`/workspaces/${workspaceId}/artifacts/${row.id}`}
                            variant="subtle"
                            size="xs"
                            w="fit-content"
                          >
                            Open
                          </Button>
                        </Stack>
                      </Paper>
                    ) : row.media ? (
                      <Paper withBorder radius="sm" p="sm" bg="var(--mantine-color-gray-light)">
                        <Stack gap="xs">
                          <Box
                            h={ARTIFACT_CARD_PREVIEW_PX}
                            w="100%"
                            style={{
                              overflow: "hidden",
                              borderRadius: 8,
                              border: "1px solid var(--mantine-color-default-border)",
                              background: "var(--mantine-color-body)",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                            }}
                          >
                            {previewImageUrl ? (
                              <Box
                                component="img"
                                src={previewImageUrl}
                                alt={artifactTitle(row)}
                                style={{
                                  display: "block",
                                  width: "100%",
                                  height: "100%",
                                  objectFit: "contain",
                                }}
                              />
                            ) : (
                              <Text size="sm" c="dimmed" ta="center" px="md">
                                {mediaMeta || "Media file"}
                              </Text>
                            )}
                          </Box>
                          <div>
                            <Text size="sm" fw={500}>
                              {row.media.display_name}
                            </Text>
                            {mediaMeta ? (
                              <Text size="xs" c="dimmed">
                                {mediaMeta}
                              </Text>
                            ) : null}
                          </div>
                          <Button
                            component={Link}
                            href={`/workspaces/${workspaceId}/artifacts/${row.id}`}
                            variant="subtle"
                            size="xs"
                            w="fit-content"
                          >
                            Open
                          </Button>
                        </Stack>
                      </Paper>
                    ) : (
                      <Paper withBorder radius="sm" p="sm" bg="var(--mantine-color-gray-light)">
                        <Stack gap="xs">
                          <Box
                            h={ARTIFACT_CARD_PREVIEW_PX}
                            w="100%"
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              borderRadius: 8,
                              border: "1px solid var(--mantine-color-default-border)",
                            }}
                          >
                            <Text size="sm" c="dimmed" ta="center" px="md">
                              No inline preview for this artifact kind.
                            </Text>
                          </Box>
                          <Button
                            component={Link}
                            href={`/workspaces/${workspaceId}/artifacts/${row.id}`}
                            variant="light"
                            size="xs"
                            w="fit-content"
                          >
                            Open details
                          </Button>
                        </Stack>
                      </Paper>
                    )}

                    <Stack gap={4}>
                      <Text size="xs" c="dimmed">
                        Identity: {row.identity?.display_name ?? "None"}
                      </Text>
                      <Text size="xs" c="dimmed">
                        Job: {row.task_execution?.job_role_name || "None"}
                      </Text>
                      <Text size="xs" c="dimmed">
                        Integration:{" "}
                        {row.integration_account
                          ? `${row.integration_account.display_name || row.integration_account.external_account_id} (${row.integration_account.provider})`
                          : "None"}
                      </Text>
                    </Stack>

                    {row.integration_account ? (
                      <Button
                        component={Link}
                        href={`/workspaces/${workspaceId}/integrations/${row.integration_account.id}`}
                        variant="subtle"
                        size="xs"
                        w="fit-content"
                      >
                        Open integration
                      </Button>
                    ) : null}
                  </Stack>
                </Card>
              );
            })}
          </SimpleGrid>
        )}

        <Modal
          opened={artifactToDelete != null}
          onClose={() => {
            if (!deleteMutation.isPending) setArtifactToDelete(null);
          }}
          title="Delete artifact"
          centered
        >
          <Stack gap="md">
            <Text size="sm">
              {artifactToDelete
                ? `Remove “${artifactTitle(artifactToDelete)}” and any linked media files from storage.`
                : null}
            </Text>
            {artifactToDelete?.task_execution ? (
              <Alert color="orange" title="Task run will be removed">
                This artifact is tied to a task execution. Deleting it removes that entire run and every
                other artifact produced in the same run.
              </Alert>
            ) : null}
            {deleteMutation.isError ? (
              <Alert color="red" title="Could not delete">
                {(deleteMutation.error as Error).message}
              </Alert>
            ) : null}
            <Group justify="flex-end" gap="sm">
              <Button
                variant="default"
                onClick={() => setArtifactToDelete(null)}
                disabled={deleteMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                color="red"
                loading={deleteMutation.isPending}
                onClick={() => {
                  if (artifactToDelete) deleteMutation.mutate(artifactToDelete);
                }}
              >
                Delete
              </Button>
            </Group>
          </Stack>
        </Modal>
      </Stack>
    </Container>
  );
}
