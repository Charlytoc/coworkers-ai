"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ActionIcon,
  Avatar,
  Badge,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Paper,
  PasswordInput,
  ScrollArea,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useDisclosure, useLocalStorage } from "@mantine/hooks";
import { io, Socket } from "socket.io-client";
import { API_BASE_URL } from "@/lib/api-base";
import type { components } from "@/lib/api/schema";
import {
  ORGANIZATION_HEADER,
  SELECTED_ORG_ID_KEY,
  SELECTED_WORKSPACE_ID_KEY,
  TOKEN_KEY,
  USER_KEY,
  parseOrganization,
  type AuthUser,
} from "@/lib/auth-storage";
import { fetchWorkspaces } from "@/lib/my-workspaces";
import {
  fetchJobAssignments,
  fetchJobAssignment,
  type JobAssignment,
} from "@/lib/workspace-job-assignments";

type ApiSchemas = components["schemas"];
type AuthResponse = ApiSchemas["AuthResponse"];
type SignupRequest = ApiSchemas["SignupRequest"];
type LoginRequest = ApiSchemas["LoginRequest"];
type ApiError = ApiSchemas["ErrorResponseSchema"];

type AgenticChatMessageRequest = {
  message: string;
  job_assignment_id: string;
};

type AgenticChatMessageResponse = {
  status: string;
  conversation_id: string;
  message_id: string;
  job_assignment_id: string;
};

type AgenticChatErrorResponse = { error: string; error_code: string };

type AgenticChatHistoryMessage = {
  id: string;
  role: string;
  content: string;
  created: string;
  attachments: ChatAttachment[];
};

type AgenticChatHistoryResponse = {
  conversation_id: string | null;
  messages: AgenticChatHistoryMessage[];
};

type AgenticChatClearResponse = {
  status: string;
  had_active_conversation: boolean;
  message: string;
};

async function fetchAgenticChatHistory(
  token: string,
  organizationId: string,
  jobAssignmentId: string,
): Promise<AgenticChatHistoryResponse> {
  const url = new URL(`${API_BASE_URL}/agentic-chat/history`);
  url.searchParams.set("job_assignment_id", jobAssignmentId);
  const response = await fetch(url.toString(), {
    headers: {
      Authorization: `Bearer ${token}`,
      [ORGANIZATION_HEADER]: organizationId,
    },
  });
  const data = (await response.json()) as AgenticChatHistoryResponse | AgenticChatErrorResponse | ApiError;
  if (!response.ok) {
    const err = data as AgenticChatErrorResponse | ApiError;
    throw new Error(err.error ?? response.statusText);
  }
  return data as AgenticChatHistoryResponse;
}

async function clearAgenticConversation(
  token: string,
  organizationId: string,
  jobAssignmentId: string,
): Promise<AgenticChatClearResponse> {
  const response = await fetch(`${API_BASE_URL}/agentic-chat/conversation/clear`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      [ORGANIZATION_HEADER]: organizationId,
    },
    body: JSON.stringify({ job_assignment_id: jobAssignmentId }),
  });
  const data = (await response.json()) as AgenticChatClearResponse | AgenticChatErrorResponse | ApiError;
  if (!response.ok) {
    const err = data as AgenticChatErrorResponse | ApiError;
    throw new Error(err.error ?? response.statusText);
  }
  return data as AgenticChatClearResponse;
}

type RealtimeMessage = {
  message: {
    role: "assistant";
    content: string;
    created: string;
    attachments?: ChatAttachment[];
  };
  timestamp: string;
};

type ChatAttachment = {
  type: "artifact";
  artifact_id: string;
  kind: string;
  label: string;
  text_preview?: string;
  media?: {
    id: string;
    display_name: string;
    mime_type: string;
    byte_size: number | null;
    public_url: string | null;
  } | null;
};

type ChatEntry = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  attachments: ChatAttachment[];
};

function ChatMessageTimestamp({ createdAt }: { createdAt: string }) {
  const d = new Date(createdAt);
  const label = Number.isNaN(d.getTime()) ? "" : d.toLocaleString();
  if (!label) return null;
  return (
    <Text size="xs" c="dimmed">
      {label}
    </Text>
  );
}

function ChatAttachments({
  attachments,
  workspaceId,
}: {
  attachments: ChatAttachment[];
  workspaceId: number | null;
}) {
  if (!attachments.length) return null;
  const canOpen =
    workspaceId != null && !Number.isNaN(workspaceId) && workspaceId > 0;
  return (
    <Stack gap="xs" mt={4}>
      {attachments.map((attachment) => {
        const media = attachment.media;
        const title =
          attachment.label ||
          media?.display_name ||
          `${attachment.kind} artifact`;
        const isImage = Boolean(
          media?.public_url && media.mime_type.startsWith("image/"),
        );
        return (
          <Paper key={attachment.artifact_id} withBorder radius="md" p="xs">
            <Stack gap={6}>
              <Group justify="space-between" gap="xs" wrap="nowrap">
                <Text size="xs" fw={600} lineClamp={1}>
                  {title}
                </Text>
                <Text size="xs" c="dimmed">
                  {attachment.kind}
                </Text>
              </Group>
              {isImage ? (
                <Box
                  component="img"
                  src={media!.public_url!}
                  alt={title}
                  style={{
                    display: "block",
                    width: "100%",
                    maxHeight: 360,
                    objectFit: "contain",
                    borderRadius: 8,
                  }}
                />
              ) : attachment.text_preview ? (
                <Text size="xs" c="dimmed" lineClamp={4} style={{ whiteSpace: "pre-wrap" }}>
                  {attachment.text_preview}
                </Text>
              ) : null}
              {canOpen ? (
                <Button
                  component={Link}
                  href={`/workspaces/${workspaceId}/artifacts/${attachment.artifact_id}`}
                  size="xs"
                  variant="light"
                  w="fit-content"
                >
                  Open
                </Button>
              ) : null}
            </Stack>
          </Paper>
        );
      })}
    </Stack>
  );
}

const REALTIME_URL = process.env.NEXT_PUBLIC_REALTIME_URL ?? "http://localhost:3001";

export default function ChatPage() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearchParams();
  const jobId = searchParams.get("job");
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [status, setStatus] = useState("Not connected");
  const [user, setUser] = useLocalStorage<AuthUser | null>({
    key: USER_KEY,
    defaultValue: null,
    getInitialValueInEffect: true,
  });
  const [token, setToken] = useLocalStorage<string | null>({
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
  const chatArtifactWorkspaceId = useMemo(() => {
    const raw = searchParams.get("workspace");
    if (raw) {
      const n = Number.parseInt(raw, 10);
      if (!Number.isNaN(n) && n > 0) return n;
    }
    return selectedWorkspaceId;
  }, [searchParams, selectedWorkspaceId]);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [waiting, setWaiting] = useState(false);
  const [clearModalOpened, { open: openClearModal, close: closeClearModal }] = useDisclosure(false);
  const socketRef = useRef<Socket | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);

  const authMutation = useMutation({
    mutationFn: async (payload: {
      mode: "login" | "signup";
      body: LoginRequest | SignupRequest;
    }) => {
      const endpoint = payload.mode === "login" ? "/auth/login" : "/auth/signup";
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload.body),
      });
      const data = (await response.json()) as AuthResponse | ApiError;
      if (!response.ok) {
        throw new Error((data as ApiError).error ?? response.statusText);
      }
      return data as AuthResponse;
    },
    onSuccess: (data) => {
      setToken(data.api_token);
      setUser(data.user);
      setStatus("Not connected");
      router.replace(data.user.onboarding_completed ? "/dashboard" : "/onboarding");
    },
    onError: (err: Error) => {
      setStatus(`Auth error: ${err.message}`);
    },
  });

  const sendMessageMutation = useMutation({
    mutationFn: async (payload: {
      token: string;
      message: string;
      organizationId: string;
      jobAssignmentId: string;
    }) => {
      const response = await fetch(`${API_BASE_URL}/agentic-chat/messages`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${payload.token}`,
          [ORGANIZATION_HEADER]: String(payload.organizationId),
        },
        body: JSON.stringify({
          message: payload.message,
          job_assignment_id: payload.jobAssignmentId,
        } satisfies AgenticChatMessageRequest),
      });
      const data = (await response.json()) as
        | AgenticChatMessageResponse
        | AgenticChatErrorResponse
        | ApiError;
      if (!response.ok) {
        const err = data as AgenticChatErrorResponse | ApiError;
        const msg = err.error ?? response.statusText;
        const code = (err as AgenticChatErrorResponse).error_code;
        if (code === "JOB_DISABLED") {
          throw new Error("This job is disabled. Enable it on the job assignment page to send messages.");
        }
        if (code === "JOB_HAS_NO_IDENTITIES") {
          throw new Error("This job has no cyber identity. Add one on the job assignment page.");
        }
        throw new Error(msg);
      }
      return data as AgenticChatMessageResponse;
    },
    onMutate: ({ message }) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-user`,
          role: "user",
          content: message,
          createdAt: new Date().toISOString(),
          attachments: [],
        },
      ]);
      setWaiting(true);
    },
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: [
          "agentic-chat-history",
          variables.token,
          variables.organizationId,
          variables.jobAssignmentId,
        ],
      });
    },
    onError: (err: Error) => {
      setStatus(`Chat error: ${err.message}`);
      setWaiting(false);
    },
  });

  const activeOrganizationId = useMemo(() => {
    if (!user) return null;
    const fromUser = parseOrganization(user.organization).id;
    const picked = selectedOrgId != null ? String(selectedOrgId) : null;
    return picked ?? fromUser ?? null;
  }, [user, selectedOrgId]);

  const historyEnabled = Boolean(user && token && activeOrganizationId && jobId);

  const {
    data: chatHistory,
    isPending: historyPending,
    isError: historyError,
    error: historyErr,
  } = useQuery({
    queryKey: ["agentic-chat-history", token, activeOrganizationId, jobId],
    queryFn: () => fetchAgenticChatHistory(token!, activeOrganizationId!, jobId!),
    enabled: historyEnabled,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    setMessages([]);
  }, [jobId]);

  useEffect(() => {
    if (!chatHistory?.messages) return;
    setMessages(
      chatHistory.messages.map((m) => ({
        id: m.id,
        role: m.role === "assistant" ? "assistant" : "user",
        content: m.content || "",
        createdAt: m.created,
        attachments: (m.attachments ?? []) as ChatAttachment[],
      })),
    );
  }, [chatHistory]);

  useEffect(() => {
    if (!historyError || !(historyErr instanceof Error)) return;
    setStatus(`History: ${historyErr.message}`);
  }, [historyError, historyErr]);

  const needsJobPicker = Boolean(user && token && activeOrganizationId && !jobId);

  const { data: workspacesData } = useQuery({
    queryKey: ["workspaces", token, activeOrganizationId],
    queryFn: () => fetchWorkspaces(token!, activeOrganizationId!),
    enabled: needsJobPicker,
    staleTime: 30_000,
  });

  const { data: chatEligibleJobs, isPending: jobsPickerPending } = useQuery<
    (JobAssignment & { workspace_name: string })[]
  >({
    queryKey: [
      "chat-eligible-jobs",
      token,
      activeOrganizationId,
      (workspacesData ?? []).map((w) => w.id).join(","),
    ],
    queryFn: async () => {
      const workspaces = workspacesData ?? [];
      const lists = await Promise.all(
        workspaces.map((ws) =>
          fetchJobAssignments(token!, activeOrganizationId!, ws.id)
            .then((rows) =>
              rows
                .filter(
                  (j) =>
                    j.enabled && j.identity_id != null,
                )
                .map((j) => ({ ...j, workspace_name: ws.name })),
            )
            .catch(() => []),
        ),
      );
      return lists.flat();
    },
    enabled: needsJobPicker && Array.isArray(workspacesData),
    staleTime: 15_000,
  });

  const workspaceIdForJobHeader =
    chatArtifactWorkspaceId != null &&
    !Number.isNaN(chatArtifactWorkspaceId) &&
    chatArtifactWorkspaceId > 0
      ? chatArtifactWorkspaceId
      : null;

  const { data: activeChatJob } = useQuery({
    queryKey: [
      "chat-header-job",
      token,
      activeOrganizationId,
      workspaceIdForJobHeader,
      jobId,
    ],
    queryFn: () =>
      fetchJobAssignment(token!, activeOrganizationId!, workspaceIdForJobHeader!, jobId!),
    enabled: Boolean(
      token &&
        activeOrganizationId &&
        jobId &&
        workspaceIdForJobHeader != null,
    ),
    staleTime: 60_000,
  });

  const canSend = useMemo(
    () =>
      Boolean(
        user &&
          token &&
          activeOrganizationId != null &&
          jobId &&
          input.trim().length > 0 &&
          !waiting &&
          !sendMessageMutation.isPending
      ),
    [input, token, user, activeOrganizationId, jobId, waiting, sendMessageMutation.isPending]
  );

  const clearConversationMutation = useMutation({
    mutationFn: async () => {
      if (!token || activeOrganizationId == null || !jobId) {
        throw new Error("Missing session");
      }
      return clearAgenticConversation(token, activeOrganizationId, jobId);
    },
    onSuccess: (data) => {
      closeClearModal();
      setMessages([]);
      setStatus(data.message);
      void queryClient.invalidateQueries({
        queryKey: ["agentic-chat-history", token, activeOrganizationId, jobId],
      });
    },
    onError: (err: Error) => {
      setStatus(`Clear error: ${err.message}`);
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, waiting]);

  useEffect(() => {
    if (!user) return;
    const socket = io(REALTIME_URL, {
      transports: ["websocket", "polling"],
      timeout: 10000,
    });
    socketRef.current = socket;
    socket.on("connect", () => {
      setStatus("connected");
      socket.emit("join-user", { userId: user.id });
    });
    socket.on("room-joined", (data) => {
      setStatus(`Joined ${data.room}`);
    });
    socket.on("agentic-chat-message", (payload: RealtimeMessage) => {
      const createdAt =
        payload.message.created || payload.timestamp || new Date().toISOString();
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant`,
          role: "assistant",
          content: payload.message.content,
          createdAt,
          attachments: payload.message.attachments ?? [],
        },
      ]);
      setWaiting(false);
    });
    socket.on("connect_error", () => {
      setStatus("connection error");
    });
    return () => {
      socket.disconnect();
      socketRef.current = null;
    };
  }, [user]);

  function submitAuth(e: FormEvent) {
    e.preventDefault();
    const body: LoginRequest | SignupRequest =
      mode === "login"
        ? { email, password }
        : { email, password, first_name: firstName || undefined, last_name: lastName || undefined };
    authMutation.mutate({ mode, body });
  }

  function sendMessage(e?: FormEvent) {
    e?.preventDefault();
    if (
      !user ||
      !token ||
      activeOrganizationId == null ||
      !jobId ||
      !input.trim() ||
      waiting ||
      sendMessageMutation.isPending
    ) {
      return;
    }
    const content = input.trim();
    setInput("");
    sendMessageMutation.mutate({
      token,
      message: content,
      organizationId: activeOrganizationId,
      jobAssignmentId: jobId,
    });
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  const userInitial = user?.email?.[0]?.toUpperCase() ?? "U";

  if (!user) {
    return (
      <Center h="100vh" bg="var(--mantine-color-body)">
        <Paper w={380} p="xl" radius="lg" shadow="md" withBorder>
          <Stack gap="lg">
            <Stack gap={4}>
              <Title order={2} fw={700}>
                {mode === "login" ? "Welcome back" : "Create account"}
              </Title>
              <Text c="dimmed" size="sm">
                {mode === "login"
                  ? "Sign in to your account to continue"
                  : "Fill in your details to get started"}
              </Text>
            </Stack>

            <form onSubmit={submitAuth}>
              <Stack gap="sm">
                {mode === "signup" && (
                  <Group grow>
                    <TextInput
                      label="First name"
                      placeholder="Jane"
                      value={firstName}
                      onChange={(e) => setFirstName(e.currentTarget.value)}
                    />
                    <TextInput
                      label="Last name"
                      placeholder="Doe"
                      value={lastName}
                      onChange={(e) => setLastName(e.currentTarget.value)}
                    />
                  </Group>
                )}
                <TextInput
                  label="Email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.currentTarget.value)}
                  required
                />
                <PasswordInput
                  label="Password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.currentTarget.value)}
                  required
                />
                <Button type="submit" fullWidth mt="xs" loading={authMutation.isPending}>
                  {mode === "login" ? "Sign in" : "Create account"}
                </Button>
              </Stack>
            </form>

            <Text size="sm" ta="center" c="dimmed">
              {mode === "login" ? "Don't have an account? " : "Already have an account? "}
              <Text
                span
                c="blue"
                style={{ cursor: "pointer" }}
                onClick={() => setMode(mode === "login" ? "signup" : "login")}
              >
                {mode === "login" ? "Sign up" : "Sign in"}
              </Text>
            </Text>
          </Stack>
        </Paper>
      </Center>
    );
  }

  if (!jobId) {
    const jobsHref =
      selectedWorkspaceId != null
        ? `/workspaces/${selectedWorkspaceId}/job-assignments`
        : "/workspace";
    const rows = chatEligibleJobs ?? [];
    return (
      <Center style={{ flex: 1 }} p="xl">
        <Paper withBorder radius="md" p="xl" maw={560} w="100%">
          <Stack gap="md">
            <div>
              <Title order={3}>Pick a job assignment</Title>
              <Text c="dimmed" size="sm" mt={4}>
                Web chat runs as a specific workspace job (instructions, tools, and persona). Choose
                an enabled job that has at least one cyber identity, or create jobs from the job
                assignments page.
              </Text>
            </div>

            {jobsPickerPending ? (
              <Center py="md">
                <Loader size="sm" />
              </Center>
            ) : rows.length === 0 ? (
              <Text c="dimmed" size="sm">
                No eligible jobs found. Create a job assignment with a cyber identity and ensure it is
                enabled.
              </Text>
            ) : (
              <Stack gap="xs">
                {rows.map((row) => (
                  <Button
                    key={row.id}
                    variant="light"
                    justify="space-between"
                    rightSection={<Badge variant="outline">{row.workspace_name}</Badge>}
                    onClick={() =>
                      router.push(`/chat?job=${encodeURIComponent(row.id)}&workspace=${row.workspace_id}`)
                    }
                  >
                    <Text size="sm" lineClamp={2} ta="left">
                      {row.role_name}
                    </Text>
                  </Button>
                ))}
              </Stack>
            )}

            <Button component={Link} href={jobsHref} variant="default">
              Job assignments
            </Button>
          </Stack>
        </Paper>
      </Center>
    );
  }

  return (
    <Box
      flex={1}
      mih={0}
      style={{ display: "flex", flexDirection: "column", background: "var(--mantine-color-body)" }}
    >
      <Box
        px="lg"
        py="sm"
        style={{
          borderBottom: "1px solid var(--mantine-color-default-border)",
          background: "var(--mantine-color-default)",
          flexShrink: 0,
        }}
      >
        <Group gap="sm" justify="space-between">
          <Group gap="sm">
            <Avatar color="blue" radius="xl" size="sm">
              {userInitial}
            </Avatar>
            <Box>
              <Text size="sm" fw={600} lh={1.2}>
                {activeChatJob?.role_name ?? "Web chat"}
              </Text>
              <Text size="xs" c={status === "connected" || status.startsWith("Joined") ? "teal" : "dimmed"}>
                {status.startsWith("Joined") ? "● Online" : status === "connected" ? "● Online" : "○ " + status}
              </Text>
            </Box>
          </Group>
          <Group gap="xs">
            <Button
              size="xs"
              variant="light"
              color="gray"
              onClick={openClearModal}
              disabled={
                !token || activeOrganizationId == null || !jobId || clearConversationMutation.isPending
              }
            >
              Clear conversation
            </Button>
            <Badge variant="light" color="violet" title={jobId}>
              Job: {activeChatJob?.role_name?.trim() || `${jobId.slice(0, 8)}…`}
            </Badge>
            <ActionIcon
              size="sm"
              variant="subtle"
              onClick={() => router.replace("/chat")}
              aria-label="Leave chat job"
              title="Pick another job"
            >
              ✕
            </ActionIcon>
          </Group>
        </Group>
      </Box>

      <Modal
        opened={clearModalOpened}
        onClose={closeClearModal}
        title="Clear conversation"
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            This archives the current chat thread. The assistant will not see earlier messages on your
            next send (same as /clear in Telegram).
          </Text>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={closeClearModal}>
              Cancel
            </Button>
            <Button
              color="orange"
              loading={clearConversationMutation.isPending}
              onClick={() => clearConversationMutation.mutate()}
            >
              Clear
            </Button>
          </Group>
        </Stack>
      </Modal>

      <ScrollArea style={{ flex: 1 }} viewportRef={viewportRef} px="md" py="sm">
        <Stack gap="md" py="sm" maw={720} mx="auto">
          {messages.length === 0 && (
            <Center h={200}>
              {historyPending ? (
                <Loader size="sm" />
              ) : (
                <Stack align="center" gap="xs">
                  <Text size="xl">👋</Text>
                  <Text fw={500}>How can I help you today?</Text>
                  <Text size="sm" c="dimmed">
                    Ask me anything — I have access to your profile info.
                  </Text>
                </Stack>
              )}
            </Center>
          )}

          {messages.map((m) =>
            m.role === "user" ? (
              <Group key={m.id} justify="flex-end" align="flex-end" gap="xs">
                <Stack gap={4} align="flex-end" maw="75%">
                  <Paper
                    px="md"
                    py="sm"
                    radius="xl"
                    style={{
                      background: "var(--mantine-color-blue-6)",
                      borderBottomRightRadius: 4,
                    }}
                  >
                    <Text size="sm" c="white" style={{ whiteSpace: "pre-wrap" }}>
                      {m.content}
                    </Text>
                    <ChatAttachments
                      attachments={m.attachments}
                      workspaceId={chatArtifactWorkspaceId}
                    />
                  </Paper>
                  <ChatMessageTimestamp createdAt={m.createdAt} />
                </Stack>
                <Avatar color="blue" radius="xl" size="sm">
                  {userInitial}
                </Avatar>
              </Group>
            ) : (
              <Group key={m.id} align="flex-end" gap="xs">
                <Avatar color="violet" radius="xl" size="sm">
                  AI
                </Avatar>
                <Stack gap={4} align="flex-start" maw="75%">
                  <Paper
                    px="md"
                    py="sm"
                    radius="xl"
                    style={{
                      background: "var(--mantine-color-default)",
                      border: "1px solid var(--mantine-color-default-border)",
                      borderBottomLeftRadius: 4,
                    }}
                  >
                    <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                      {m.content}
                    </Text>
                    <ChatAttachments
                      attachments={m.attachments}
                      workspaceId={chatArtifactWorkspaceId}
                    />
                  </Paper>
                  <ChatMessageTimestamp createdAt={m.createdAt} />
                </Stack>
              </Group>
            )
          )}

          {waiting && (
            <Group align="flex-end" gap="xs">
              <Avatar color="violet" radius="xl" size="sm">
                AI
              </Avatar>
              <Paper
                px="md"
                py="sm"
                radius="xl"
                style={{
                  background: "var(--mantine-color-default)",
                  border: "1px solid var(--mantine-color-default-border)",
                  borderBottomLeftRadius: 4,
                }}
              >
                <Loader size="xs" type="dots" />
              </Paper>
            </Group>
          )}

          <div ref={bottomRef} />
        </Stack>
      </ScrollArea>

      <Box
        px="md"
        py="sm"
        style={{
          borderTop: "1px solid var(--mantine-color-default-border)",
          background: "var(--mantine-color-default)",
          flexShrink: 0,
        }}
      >
        <Box maw={720} mx="auto">
          <form onSubmit={sendMessage}>
            <Paper
              radius="xl"
              withBorder
              style={{
                display: "flex",
                alignItems: "flex-end",
                gap: 8,
                padding: "8px 8px 8px 16px",
                borderColor: "var(--mantine-color-default-border)",
              }}
            >
              <Textarea
                style={{ flex: 1 }}
                placeholder="Message AI Assistant… (Enter to send, Shift+Enter for new line)"
                value={input}
                onChange={(e) => setInput(e.currentTarget.value)}
                onKeyDown={handleKeyDown}
                autosize
                minRows={1}
                maxRows={6}
                variant="unstyled"
              />
              <ActionIcon
                type="submit"
                size="lg"
                radius="xl"
                disabled={!canSend}
                color="blue"
                variant={canSend ? "filled" : "subtle"}
              >
                ↑
              </ActionIcon>
            </Paper>
          </form>
        </Box>
      </Box>
    </Box>
  );
}
