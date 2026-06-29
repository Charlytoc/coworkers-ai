"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Anchor,
  Button,
  Center,
  Container,
  Loader,
  Paper,
  PasswordInput,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useWorkspacePage } from "@/hooks/use-workspace-page";
import { fetchCyberIdentities } from "@/lib/workspace-cyber-identities";
import { connectTelegramBot } from "@/lib/telegram-integration";
import { getInstagramOAuthUrl } from "@/lib/instagram-integration";

export default function ConnectIntegrationPage() {
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

  const [cyberIdentityId, setCyberIdentityId] = useState<string | null>(null);
  const [useCase, setUseCase] = useState("");

  const [botToken, setBotToken] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [igLoading, setIgLoading] = useState<"instagram_login" | "facebook_login" | null>(null);
  const [igError, setIgError] = useState<string | null>(
    searchParams.get("instagram_error"),
  );

  const baseEnabled = workspaceReady && Boolean(token) && Boolean(orgId) && !Number.isNaN(workspaceId);

  const { data: identities, isPending: identitiesPending } = useQuery({
    queryKey: ["cyber-identities", token, orgId, workspaceId],
    queryFn: () => fetchCyberIdentities(token!, orgId!, workspaceId),
    enabled: baseEnabled,
    staleTime: 15_000,
  });

  const identityOptions = useMemo(
    () =>
      (identities ?? []).map((i) => ({
        value: i.id,
        label: `${i.display_name} (${i.type})`,
      })),
    [identities],
  );

  async function connectInstagram(authMethod: "instagram_login" | "facebook_login") {
    if (!token || !orgId || !cyberIdentityId) return;
    setIgError(null);
    setIgLoading(authMethod);
    try {
      const { oauth_url } = await getInstagramOAuthUrl(token, orgId, workspaceId, {
        cyber_identity_id: cyberIdentityId,
        use_case: useCase.trim(),
        auth_method: authMethod,
      });
      window.location.href = oauth_url;
    } catch (err) {
      setIgError((err as Error).message);
      setIgLoading(null);
    }
  }

  const connectMutation = useMutation({
    mutationFn: () =>
      connectTelegramBot(token!, orgId!, workspaceId, {
        bot_token: botToken.trim(),
        display_name: displayName.trim() || null,
        cyber_identity_id: cyberIdentityId!,
        use_case: useCase.trim(),
      }),
    onSuccess: async () => {
      setFormError(null);
      await queryClient.invalidateQueries({
        queryKey: ["workspace-integrations", token, orgId, workspaceId],
      });
      router.push(`/workspaces/${workspaceId}/integrations`);
    },
    onError: (err: Error) => {
      setFormError(err.message);
    },
  });

  const onboardingReady = Boolean(cyberIdentityId) && useCase.trim().length > 0;

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
    <Container size="sm" py="xl" style={{ flex: 1 }}>
      <Stack gap="lg">
        <div>
          <Button component={Link} href={`/workspaces/${workspaceId}/integrations`} variant="subtle" size="xs" mb="xs">
            ← Integrations
          </Button>
          <Title order={2}>Connect integration</Title>
          <Text size="sm" c="dimmed" mt={4}>
            Workspace: <strong>{workspace.name}</strong>
          </Text>
        </div>

        {workspaceMismatch ? (
          <Alert color="yellow" title="Different workspace selected in sidebar">
            The URL points to workspace id {workspaceId}, but the sidebar has workspace {selectedWorkspaceId} selected.
            You can still continue if you have access.
          </Alert>
        ) : null}

        <Paper withBorder radius="md" p="lg">
          <Stack gap="md">
            <Title order={3}>How you will use this account</Title>
            <Text size="sm" c="dimmed">
              Pick the workspace persona that will own messages on this channel and describe what you want the
              assistant to do. We use this to generate a tailored job after the connection succeeds.
            </Text>
            {identitiesPending ? (
              <Loader size="sm" />
            ) : (
              <Select
                label="Cyber identity"
                placeholder="Choose who runs this integration"
                data={identityOptions}
                value={cyberIdentityId}
                onChange={setCyberIdentityId}
                searchable
                required
              />
            )}
            <Textarea
              label="Use case"
              placeholder="e.g. Reply to customer DMs in Spanish, escalate leads to sales, send appointment reminders…"
              value={useCase}
              onChange={(e) => setUseCase(e.currentTarget.value)}
              minRows={4}
              autosize
              maxRows={12}
              required
            />
          </Stack>
        </Paper>

        <Paper withBorder radius="md" p="lg">
          <Stack gap="md">
            <Title order={3}>Telegram</Title>
            <Text size="sm" c="dimmed">
              Create a bot with{" "}
              <Anchor href="https://t.me/BotFather" target="_blank" rel="noreferrer" size="sm">
                @BotFather
              </Anchor>
              , then paste the bot token here. After connecting you will return to Integrations. New chatters get a
              12-digit code; approve them on the Integrations page.
            </Text>
            {formError ? (
              <Alert color="red" title="Could not connect">
                {formError}
              </Alert>
            ) : null}
            <PasswordInput
              label="Bot token"
              placeholder="123456789:ABC..."
              value={botToken}
              onChange={(e) => setBotToken(e.currentTarget.value)}
              disabled={connectMutation.isPending}
              required
            />
            <TextInput
              label="Display name (optional)"
              placeholder="@MyBot or label shown in the app"
              value={displayName}
              onChange={(e) => setDisplayName(e.currentTarget.value)}
              disabled={connectMutation.isPending}
            />
            <Button
              onClick={() => connectMutation.mutate()}
              loading={connectMutation.isPending}
              disabled={!botToken.trim() || !onboardingReady}
            >
              Connect Telegram bot
            </Button>
          </Stack>
        </Paper>

        <Paper withBorder radius="md" p="lg">
          <Stack gap="md">
            <Title order={3}>Instagram</Title>
            <Text size="xs" c="dimmed">
              Need help?{" "}
              <Anchor
                href="https://help.instagram.com/502981923235522"
                target="_blank"
                rel="noreferrer"
                size="xs"
              >
                How to switch to a Professional account
              </Anchor>
            </Text>
            {igError ? (
              <Alert color="red" title="Could not connect Instagram" onClose={() => setIgError(null)} withCloseButton>
                {igError}
              </Alert>
            ) : null}

            <Paper withBorder radius="sm" p="md">
              <Stack gap="sm">
                <Text fw={600} size="sm">
                  Connect for publish &amp; DMs
                </Text>
                <Text size="sm" c="dimmed">
                  Instagram Login only. No Facebook Page required. Publish feed posts and receive or reply to DMs.
                  Post analytics, comment moderation, and delete are not available on this path.
                </Text>
                <Button
                  onClick={() => connectInstagram("instagram_login")}
                  loading={igLoading === "instagram_login"}
                  disabled={!token || !orgId || !onboardingReady || igLoading !== null}
                  variant="light"
                >
                  Connect with Instagram Login
                </Button>
              </Stack>
            </Paper>

            <Paper withBorder radius="sm" p="md">
              <Stack gap="sm">
                <Text fw={600} size="sm">
                  Connect full Instagram management
                </Text>
                <Text size="sm" c="dimmed">
                  Facebook Login for Business. Requires a Professional Instagram account linked to a Facebook Page
                  you manage. Enables insights, comments, delete, and future Facebook or Messenger features.
                </Text>
                <Button
                  onClick={() => connectInstagram("facebook_login")}
                  loading={igLoading === "facebook_login"}
                  disabled={!token || !orgId || !onboardingReady || igLoading !== null}
                  variant="gradient"
                  gradient={{ from: "grape", to: "pink", deg: 135 }}
                >
                  Connect with Facebook Login
                </Button>
              </Stack>
            </Paper>
          </Stack>
        </Paper>
      </Stack>
    </Container>
  );
}
