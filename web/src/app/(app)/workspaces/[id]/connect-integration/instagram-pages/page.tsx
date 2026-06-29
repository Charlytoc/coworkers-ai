"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Center,
  Container,
  Loader,
  Paper,
  Radio,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useWorkspacePage } from "@/hooks/use-workspace-page";
import {
  completeFacebookPageSelection,
  fetchFacebookPagesPending,
} from "@/lib/instagram-integration";

export default function InstagramPagesPickerPage() {
  const {
    router,
    workspaceId,
    token,
    orgId,
    sessionOk,
    displayUser,
    workspaceReady,
  } = useWorkspacePage();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const pending = searchParams.get("pending") ?? "";

  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const enabled = workspaceReady && Boolean(token) && Boolean(orgId) && pending.length > 0;

  const { data, isPending, error } = useQuery({
    queryKey: ["instagram-facebook-pages", token, orgId, workspaceId, pending],
    queryFn: () => fetchFacebookPagesPending(token!, orgId!, workspaceId, pending),
    enabled,
    staleTime: 0,
  });

  async function onComplete() {
    if (!token || !orgId || !selectedPageId) return;
    setSubmitError(null);
    setSubmitting(true);
    try {
      await completeFacebookPageSelection(token, orgId, workspaceId, {
        pending,
        page_id: selectedPageId,
      });
      await queryClient.invalidateQueries({
        queryKey: ["workspace-integrations", token, orgId, workspaceId],
      });
      router.push(`/workspaces/${workspaceId}/integrations?instagram_connected=true`);
    } catch (err) {
      setSubmitError((err as Error).message);
      setSubmitting(false);
    }
  }

  if (!sessionOk || !displayUser) {
    return (
      <Center style={{ flex: 1 }}>
        <Loader size="sm" />
      </Center>
    );
  }

  if (!pending) {
    return (
      <Container size="sm" py="xl">
        <Alert color="red" title="Missing selection">
          No pending Facebook Page selection was found. Start the connection flow again from Integrations.
        </Alert>
        <Button component={Link} href={`/workspaces/${workspaceId}/connect-integration`} variant="light" mt="md">
          Back to connect
        </Button>
      </Container>
    );
  }

  return (
    <Container size="sm" py="xl" style={{ flex: 1 }}>
      <Stack gap="lg">
        <div>
          <Button
            component={Link}
            href={`/workspaces/${workspaceId}/connect-integration`}
            variant="subtle"
            size="xs"
            mb="xs"
          >
            ← Connect integration
          </Button>
          <Title order={2}>Choose Instagram account</Title>
          <Text size="sm" c="dimmed" mt={4}>
            Multiple Facebook Pages with linked Instagram accounts were found. Pick the one to connect.
          </Text>
        </div>

        {isPending ? (
          <Center py="xl">
            <Loader size="sm" />
          </Center>
        ) : error ? (
          <Alert color="red" title="Could not load pages">
            {(error as Error).message}
          </Alert>
        ) : (
          <Paper withBorder radius="md" p="lg">
            <Stack gap="md">
              <Radio.Group value={selectedPageId} onChange={setSelectedPageId}>
                <Stack gap="sm">
                  {(data?.pages ?? []).map((page) => (
                    <Radio
                      key={page.page_id}
                      value={page.page_id}
                      label={page.display_label}
                      description={`Page id ${page.page_id} · IG ${page.ig_user_id}`}
                    />
                  ))}
                </Stack>
              </Radio.Group>
              {submitError ? (
                <Alert color="red" title="Could not connect">
                  {submitError}
                </Alert>
              ) : null}
              <Button
                onClick={onComplete}
                loading={submitting}
                disabled={!selectedPageId || (data?.pages.length ?? 0) === 0}
              >
                Connect selected account
              </Button>
            </Stack>
          </Paper>
        )}
      </Stack>
    </Container>
  );
}
