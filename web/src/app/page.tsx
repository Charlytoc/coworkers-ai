"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Anchor,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { readStoredAuth } from "@/lib/auth-storage";

export default function Home() {
  const router = useRouter();
  const [phase, setPhase] = useState<"checking" | "landing">("checking");

  useEffect(() => {
    const { token, user } = readStoredAuth();
    if (token && user) {
      router.replace(user.onboarding_completed ? "/dashboard" : "/onboarding");
      return;
    }
    setPhase("landing");
  }, [router]);

  if (phase === "checking") {
    return (
      <Center h="100vh" bg="var(--mantine-color-body)">
        <Loader size="sm" />
      </Center>
    );
  }

  return (
    <Center h="100vh" bg="var(--mantine-color-body)">
      <Container size="sm" py="xl">
        <Stack gap="xl" align="center" ta="center">
          <Stack gap="xs" maw={480}>
            <Title order={1} fw={800}>
              Coworkers AI
            </Title>
            <Text c="dimmed" size="lg">
              Virtual workers for your organization — chat, tasks, and realtime collaboration.
            </Text>
          </Stack>
          <Group gap="sm">
            <Button component={Link} href="/dashboard" size="md">
              Open app
            </Button>
            <Button component={Link} href="/chat" variant="default" size="md">
              Sign in
            </Button>
          </Group>
          <Text size="sm" c="dimmed">
            <Anchor component={Link} href="/privacy-policy" c="dimmed" underline="hover">
              Privacy Policy
            </Anchor>
            {" · "}
            <Anchor component={Link} href="/terms-of-service" c="dimmed" underline="hover">
              Terms of Service
            </Anchor>
          </Text>
        </Stack>
      </Container>
    </Center>
  );
}
