"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Box,
  Center,
  Container,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { useLocalStorage } from "@mantine/hooks";
import {
  IconMessage2,
  IconBriefcase,
  IconUser,
  IconPlug,
  IconPhoto,
  IconSettings,
} from "@tabler/icons-react";
import {
  SELECTED_WORKSPACE_ID_KEY,
  TOKEN_KEY,
  USER_KEY,
  readStoredAuth,
  type AuthUser,
} from "@/lib/auth-storage";

type NavCard = {
  label: string;
  description: string;
  icon: React.ReactNode;
  href: string;
};

function DashCard({ label, description, icon, href }: NavCard) {
  return (
    <UnstyledButton
      component={Link}
      href={href}
      style={{
        display: "block",
        padding: "var(--mantine-spacing-md)",
        borderRadius: "var(--mantine-radius-md)",
        border: "1px solid var(--mantine-color-dark-5)",
        background: "var(--mantine-color-dark-6)",
        transition: "border-color 120ms ease, background 120ms ease",
      }}
      styles={{
        root: {
          "&:hover": {
            borderColor: "var(--mantine-color-wine-6)",
            background: "var(--mantine-color-dark-5)",
          },
        },
      }}
    >
      <Stack gap={8}>
        <Box c="wine">{icon}</Box>
        <Text fw={600} size="sm">
          {label}
        </Text>
        <Text size="xs" c="dimmed" lh={1.4}>
          {description}
        </Text>
      </Stack>
    </UnstyledButton>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [sessionOk, setSessionOk] = useState(false);
  const [user] = useLocalStorage<AuthUser | null>({
    key: USER_KEY,
    defaultValue: null,
    getInitialValueInEffect: true,
  });
  const [selectedWorkspaceId] = useLocalStorage<number | null>({
    key: SELECTED_WORKSPACE_ID_KEY,
    defaultValue: null,
    getInitialValueInEffect: true,
  });

  useEffect(() => {
    const { user: stored } = readStoredAuth();
    if (!stored) {
      router.replace("/chat");
      return;
    }
    setSessionOk(true);
  }, [router]);

  const displayUser = user ?? readStoredAuth().user;

  if (!sessionOk || !displayUser) {
    return (
      <Center style={{ flex: 1 }}>
        <Loader size="sm" />
      </Center>
    );
  }

  const displayName =
    [displayUser.first_name, displayUser.last_name].filter(Boolean).join(" ").trim() ||
    displayUser.email;

  const wsBase = selectedWorkspaceId ? `/workspaces/${selectedWorkspaceId}` : null;

  const cards: NavCard[] = [
    {
      label: "Chat",
      description: "Talk to your AI assistant, create content, and schedule tasks.",
      icon: <IconMessage2 size={22} />,
      href: wsBase ? `/chat?workspace=${selectedWorkspaceId}` : "/chat",
    },
    ...(wsBase
      ? [
          {
            label: "Jobs",
            description: "Manage job assignments and configure what your agents do.",
            icon: <IconBriefcase size={22} />,
            href: `${wsBase}/job-assignments`,
          },
          {
            label: "Cyber identities",
            description: "Define the personas your AI agents adopt when responding.",
            icon: <IconUser size={22} />,
            href: `${wsBase}/cyber-identities`,
          },
          {
            label: "Accounts",
            description: "View and connect your Telegram or Instagram accounts.",
            icon: <IconPlug size={22} />,
            href: `${wsBase}/integrations`,
          },
          {
            label: "Artifacts",
            description: "Browse images, text, and other content your agents have created.",
            icon: <IconPhoto size={22} />,
            href: `${wsBase}/artifacts`,
          },
        ]
      : []),
    {
      label: "Settings",
      description: "Manage your account and organization settings.",
      icon: <IconSettings size={22} />,
      href: "/settings",
    },
  ];

  return (
    <Container size="md" py="xl" style={{ flex: 1 }}>
      <Stack gap="xl">
        <div>
          <Title order={2}>Welcome back, {displayName.split(" ")[0]}</Title>
          <Text c="dimmed" mt={4} size="sm">
            What would you like to do today?
          </Text>
        </div>

        <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }} spacing="sm">
          {cards.map((card) => (
            <DashCard key={card.href} {...card} />
          ))}
        </SimpleGrid>
      </Stack>
    </Container>
  );
}
