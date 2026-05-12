"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Anchor,
  Button,
  Container,
  Loader,
  Center,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useWorkspacePage } from "@/hooks/use-workspace-page";
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

  const [botToken, setBotToken] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [igLoading, setIgLoading] = useState(false);
  const [igError, setIgError] = useState<string | null>(
    searchParams.get("instagram_error"),
  );

  async function connectInstagram() {
    if (!token || !orgId) return;
    setIgError(null);
    setIgLoading(true);
    try {
      const { oauth_url } = await getInstagramOAuthUrl(token, orgId, workspaceId);
      window.location.href = oauth_url;
    } catch (err) {
      setIgError((err as Error).message);
      setIgLoading(false);
    }
  }

  const connectMutation = useMutation({
    mutationFn: () =>
      connectTelegramBot(token!, orgId!, workspaceId, {
        bot_token: botToken.trim(),
        display_name: displayName.trim() || null,
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
              disabled={!botToken.trim()}
            >
              Connect Telegram bot
            </Button>
          </Stack>
        </Paper>

        <Paper withBorder radius="md" p="lg">
          <Stack gap="md">
            <Title order={3}>Instagram</Title>
            <Text size="sm" c="dimmed">
              Connect an Instagram Business or Creator account via Facebook Login. You will be
              redirected to Meta to authorize the app, then brought back here automatically.
              Make sure your Instagram account is linked to a Facebook Page.
            </Text>
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
            <Button
              onClick={connectInstagram}
              loading={igLoading}
              disabled={!token || !orgId}
              variant="gradient"
              gradient={{ from: "grape", to: "pink", deg: 135 }}
            >
              Connect Instagram account
            </Button>
          </Stack>
        </Paper>
      </Stack>
    </Container>
  );
}
