"use client";

import { useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  Badge,
  Button,
  Container,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useLocalStorage } from "@mantine/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchCurrentUser,
  patchActiveOrganization,
  patchCurrentUser,
} from "@/lib/account-settings";
import { fetchMyOrganizations } from "@/lib/my-organizations";
import { fetchWorkspaces, patchWorkspace } from "@/lib/my-workspaces";
import {
  SELECTED_ORG_ID_KEY,
  SELECTED_WORKSPACE_ID_KEY,
  TOKEN_KEY,
  USER_KEY,
  parseOrganization,
  readStoredAuth,
  type AuthUser,
} from "@/lib/auth-storage";

export default function SettingsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [user, setUser] = useLocalStorage<AuthUser | null>({
    key: USER_KEY,
    defaultValue: null,
    getInitialValueInEffect: true,
  });
  const [token] = useLocalStorage<string | null>({
    key: TOKEN_KEY,
    defaultValue: null,
    getInitialValueInEffect: true,
  });
  const [selectedOrgId] = useLocalStorage<string | null>({
    key: SELECTED_ORG_ID_KEY,
    defaultValue: null,
    getInitialValueInEffect: true,
  });
  const [selectedWorkspaceId] = useLocalStorage<number | null>({
    key: SELECTED_WORKSPACE_ID_KEY,
    defaultValue: null,
    getInitialValueInEffect: true,
  });

  useEffect(() => {
    if (!readStoredAuth().user) {
      router.replace("/chat");
    }
  }, [router]);

  const orgId = selectedOrgId != null ? String(selectedOrgId) : null;

  const { data: me, isPending: mePending } = useQuery({
    queryKey: ["me", token],
    queryFn: () => fetchCurrentUser(token!),
    enabled: Boolean(token),
    staleTime: 30_000,
  });

  const { data: organizations } = useQuery({
    queryKey: ["my-organizations", token],
    queryFn: () => fetchMyOrganizations(token!),
    enabled: Boolean(token),
    staleTime: 60_000,
  });

  const { data: workspaces } = useQuery({
    queryKey: ["workspaces", token, orgId],
    queryFn: () => fetchWorkspaces(token!, orgId!),
    enabled: Boolean(token) && orgId != null,
    staleTime: 30_000,
  });

  const displayUser = me ?? user ?? readStoredAuth().user;
  const primaryOrgId = displayUser ? parseOrganization(displayUser.organization).id : null;
  const canEditOrganization =
    orgId != null && primaryOrgId != null && String(primaryOrgId) === String(orgId);

  const activeOrg = useMemo(() => {
    if (!organizations?.length || orgId == null) return null;
    return organizations.find((o) => String(o.id) === orgId) ?? null;
  }, [organizations, orgId]);

  const activeWorkspace = useMemo(() => {
    if (selectedWorkspaceId == null || !workspaces?.length) return null;
    return workspaces.find((w) => w.id === selectedWorkspaceId) ?? null;
  }, [workspaces, selectedWorkspaceId]);

  const isWorkspaceMember = Boolean(activeWorkspace);

  const userMutation = useMutation({
    mutationFn: async (vars: { first_name: string; last_name: string }) => {
      if (!token) throw new Error("Not signed in.");
      return patchCurrentUser(token, {
        first_name: vars.first_name.trim(),
        last_name: vars.last_name.trim(),
      });
    },
    onSuccess: (updated) => {
      setUser(updated);
      void queryClient.invalidateQueries({ queryKey: ["me", token] });
    },
  });

  const orgMutation = useMutation({
    mutationFn: async (vars: { name: string; domain: string }) => {
      if (!token || orgId == null) throw new Error("Not signed in or no organization selected.");
      return patchActiveOrganization(token, orgId, {
        name: vars.name.trim(),
        domain: vars.domain.trim(),
      });
    },
    onSuccess: (updatedOrg) => {
      void queryClient.invalidateQueries({ queryKey: ["my-organizations", token] });
      const prev = readStoredAuth().user;
      if (prev && parseOrganization(prev.organization).id === String(updatedOrg.id)) {
        setUser({
          ...prev,
          organization: {
            id: String(updatedOrg.id),
            name: updatedOrg.name,
            domain: updatedOrg.domain,
            status: updatedOrg.status,
          },
        });
      }
    },
  });

  const workspaceMutation = useMutation({
    mutationFn: async (name: string) => {
      if (!token || orgId == null || selectedWorkspaceId == null) {
        throw new Error("Not signed in, or missing organization or workspace.");
      }
      return patchWorkspace(token, orgId, selectedWorkspaceId, name);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["workspaces", token, orgId] });
    },
  });

  if (!displayUser) {
    return (
      <Container size="sm" py="xl" style={{ flex: 1 }}>
        <Loader size="sm" />
      </Container>
    );
  }

  return (
    <Container size="sm" py="xl" style={{ flex: 1 }}>
      <Stack gap="lg">
        <div>
          <Title order={2}>Settings</Title>
          <Text size="sm" c="dimmed" mt={4}>
            Sections below reflect what you can change for the organization and workspace selected in the header
            (desktop) or sidebar (mobile).
          </Text>
        </div>

        <Paper withBorder radius="md" p="md">
          <Title order={5} mb="xs">
            What you can access here
          </Title>
          <Stack gap="xs">
            <Group gap="xs">
              <Badge color="blue" variant="light">
                User profile
              </Badge>
              <Text size="sm" c="dimmed">
                Always available while signed in.
              </Text>
            </Group>
            <Group gap="xs" align="flex-start">
              <Badge color={canEditOrganization ? "teal" : "gray"} variant="light">
                Organization
              </Badge>
              <Text size="sm" c="dimmed" maw={420}>
                {canEditOrganization
                  ? "You may edit the active organization because it is your primary organization on this account."
                  : "Editing the organization name or domain is limited to your primary organization. Switch to that organization in the header to edit it, or ask an administrator."}
              </Text>
            </Group>
            <Group gap="xs" align="flex-start">
              <Badge color={isWorkspaceMember ? "teal" : "gray"} variant="light">
                Workspace
              </Badge>
              <Text size="sm" c="dimmed" maw={420}>
                {isWorkspaceMember
                  ? "You are an active member of the selected workspace and may rename it."
                  : "Select a workspace in the sidebar to rename it."}
              </Text>
            </Group>
          </Stack>
        </Paper>

        <Paper withBorder radius="md" p="md" component="form">
          <Title order={4} mb="md">
            User
          </Title>
          {mePending ? (
            <Loader size="sm" />
          ) : (
            <UserSettingsForm
              key={`${displayUser.email}-${displayUser.first_name ?? ""}-${displayUser.last_name ?? ""}`}
              email={displayUser.email}
              firstName={displayUser.first_name ?? ""}
              lastName={displayUser.last_name ?? ""}
              loading={userMutation.isPending}
              error={userMutation.error}
              onSave={(first_name, last_name) => userMutation.mutate({ first_name, last_name })}
            />
          )}
        </Paper>

        {orgId == null ? (
          <Paper withBorder radius="md" p="md">
            <Title order={4} mb="xs">
              Organization
            </Title>
            <Text size="sm" c="dimmed">
              Select an organization first.
            </Text>
          </Paper>
        ) : canEditOrganization && activeOrg ? (
          <Paper withBorder radius="md" p="md" component="form">
            <Title order={4} mb="md">
              Organization
            </Title>
            <OrgSettingsForm
              key={`${activeOrg.id}-${activeOrg.name}-${activeOrg.domain}`}
              name={activeOrg.name}
              domain={activeOrg.domain}
              loading={orgMutation.isPending}
              error={orgMutation.error}
              onSave={(name, domain) => orgMutation.mutate({ name, domain })}
            />
          </Paper>
        ) : (
          <Paper withBorder radius="md" p="md">
            <Title order={4} mb="xs">
              Organization
            </Title>
            <Text size="sm" c="dimmed">
              {activeOrg
                ? "You are not the primary account holder for this organization, so its name and domain cannot be edited here."
                : "Loading organization…"}
            </Text>
          </Paper>
        )}

        {orgId == null ? null : !activeWorkspace ? (
          <Paper withBorder radius="md" p="md">
            <Title order={4} mb="xs">
              Workspace
            </Title>
            <Text size="sm" c="dimmed">
              No workspace selected. Create or pick one from the sidebar.
            </Text>
          </Paper>
        ) : (
          <Paper withBorder radius="md" p="md" component="form">
            <Title order={4} mb="md">
              Workspace
            </Title>
            <WorkspaceSettingsForm
              key={`${activeWorkspace.id}-${activeWorkspace.name}`}
              name={activeWorkspace.name}
              loading={workspaceMutation.isPending}
              error={workspaceMutation.error}
              onSave={(name) => workspaceMutation.mutate(name)}
            />
          </Paper>
        )}
      </Stack>
    </Container>
  );
}

function UserSettingsForm({
  email,
  firstName,
  lastName,
  loading,
  error,
  onSave,
}: {
  email: string;
  firstName: string;
  lastName: string;
  loading: boolean;
  error: Error | null;
  onSave: (first: string, last: string) => void;
}) {
  return (
    <Stack gap="sm">
      <TextInput label="Email" value={email} disabled description="Contact support to change your email." />
      <TextInput label="First name" name="first_name" defaultValue={firstName} />
      <TextInput label="Last name" name="last_name" defaultValue={lastName} />
      {error ? (
        <Text size="sm" c="red">
          {error.message}
        </Text>
      ) : null}
      <Group justify="flex-end">
        <Button
          type="submit"
          loading={loading}
          onClick={(e) => {
            e.preventDefault();
            const form = e.currentTarget.closest("form");
            if (!form) return;
            const fd = new FormData(form);
            onSave(String(fd.get("first_name") ?? ""), String(fd.get("last_name") ?? ""));
          }}
        >
          Save profile
        </Button>
      </Group>
    </Stack>
  );
}

function OrgSettingsForm({
  name,
  domain,
  loading,
  error,
  onSave,
}: {
  name: string;
  domain: string;
  loading: boolean;
  error: Error | null;
  onSave: (name: string, domain: string) => void;
}) {
  return (
    <Stack gap="sm">
      <TextInput label="Name" name="org_name" defaultValue={name} required />
      <TextInput
        label="Domain"
        name="org_domain"
        defaultValue={domain}
        required
        description="Internal identifier for this organization; not necessarily a public website."
      />
      {error ? (
        <Text size="sm" c="red">
          {error.message}
        </Text>
      ) : null}
      <Group justify="flex-end">
        <Button
          type="submit"
          loading={loading}
          onClick={(e) => {
            e.preventDefault();
            const form = e.currentTarget.closest("form");
            if (!form) return;
            const fd = new FormData(form);
            onSave(String(fd.get("org_name") ?? ""), String(fd.get("org_domain") ?? ""));
          }}
        >
          Save organization
        </Button>
      </Group>
    </Stack>
  );
}

function WorkspaceSettingsForm({
  name,
  loading,
  error,
  onSave,
}: {
  name: string;
  loading: boolean;
  error: Error | null;
  onSave: (name: string) => void;
}) {
  return (
    <Stack gap="sm">
      <TextInput label="Workspace name" name="workspace_name" defaultValue={name} required />
      {error ? (
        <Text size="sm" c="red">
          {error.message}
        </Text>
      ) : null}
      <Group justify="flex-end">
        <Button
          type="submit"
          loading={loading}
          onClick={(e) => {
            e.preventDefault();
            const form = e.currentTarget.closest("form");
            if (!form) return;
            const fd = new FormData(form);
            onSave(String(fd.get("workspace_name") ?? ""));
          }}
        >
          Save workspace
        </Button>
      </Group>
    </Stack>
  );
}
