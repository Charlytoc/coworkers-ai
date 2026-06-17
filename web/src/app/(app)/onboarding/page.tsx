"use client";

import { useState } from "react";
import { IconCheck } from "@tabler/icons-react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import {
  Button,
  Center,
  Container,
  Group,
  Stepper,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
  ThemeIcon,
} from "@mantine/core";
import { useLocalStorage } from "@mantine/hooks";
import { API_BASE_URL } from "@/lib/api-base";
import { TOKEN_KEY, USER_KEY, type AuthUser } from "@/lib/auth-storage";

export default function OnboardingPage() {
  const router = useRouter();
  const [active, setActive] = useState(0);

  const [orgName, setOrgName] = useState("");
  const [orgDescription, setOrgDescription] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");

  const [token] = useLocalStorage<string | null>({ key: TOKEN_KEY, defaultValue: null });
  const [, setUser] = useLocalStorage<AuthUser | null>({ key: USER_KEY, defaultValue: null });

  const onboardingMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/auth/onboarding`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          org_name: orgName,
          org_description: orgDescription,
          workspace_name: workspaceName,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error ?? "Something went wrong");
      }
      return res.json();
    },
    onSuccess: (data) => {
      setUser(data.user);
      setActive(2);
    },
  });

  const nextStep = () => {
    if (active === 1) {
      onboardingMutation.mutate();
      return;
    }
    setActive((s) => s + 1);
  };

  const step1Valid = orgName.trim().length > 0;
  const step2Valid = workspaceName.trim().length > 0;
  const canProceed = active === 0 ? step1Valid : active === 1 ? step2Valid : false;

  return (
    <Center mih="100vh" bg="var(--mantine-color-body)">
      <Container size="sm" w="100%" py="xl">
        <Stack gap="xl">
          <Stack gap={4} ta="center">
            <Title order={2}>Welcome to Coworkers AI</Title>
            <Text c="dimmed">Let&apos;s get your organization set up in a few quick steps.</Text>
          </Stack>

          <Stepper active={active} allowNextStepsSelect={false}>
            <Stepper.Step label="Your organization" description="Name and describe it">
              <Stack gap="md" mt="lg">
                <TextInput
                  label="Organization name"
                  placeholder="Acme Corp"
                  value={orgName}
                  onChange={(e) => setOrgName(e.currentTarget.value)}
                  required
                  autoFocus
                />
                <Textarea
                  label="Description"
                  description="What does your organization do? (optional)"
                  placeholder="We build AI-powered tools for support teams…"
                  value={orgDescription}
                  onChange={(e) => setOrgDescription(e.currentTarget.value)}
                  minRows={3}
                  autosize
                />
              </Stack>
            </Stepper.Step>

            <Stepper.Step label="First workspace" description="Create your first space">
              <Stack gap="md" mt="lg">
                <Text size="sm" c="dimmed">
                  A workspace is a completely independent space inside your organization — it has
                  its own accounts, agents, and members. You can create more workspaces later for
                  different teams or projects.
                </Text>
                <TextInput
                  label="Workspace name"
                  placeholder="Support, Marketing, Sales…"
                  value={workspaceName}
                  onChange={(e) => setWorkspaceName(e.currentTarget.value)}
                  required
                  autoFocus
                />
              </Stack>
            </Stepper.Step>

            <Stepper.Completed>
              <Stack gap="md" mt="lg" align="center" ta="center">
                <ThemeIcon size={56} radius="xl" color="teal">
                  <IconCheck size={28} />
                </ThemeIcon>
                <Title order={3}>You&apos;re all set!</Title>
                <Text c="dimmed" maw={380}>
                  Your organization <strong>{orgName}</strong> and your first workspace{" "}
                  <strong>{workspaceName}</strong> are ready to go.
                </Text>
                <Button size="md" mt="sm" onClick={() => router.replace("/dashboard")}>
                  Go to dashboard
                </Button>
              </Stack>
            </Stepper.Completed>
          </Stepper>

          {active < 2 && (
            <Group justify="flex-end">
              {active > 0 && (
                <Button variant="default" onClick={() => setActive((s) => s - 1)}>
                  Back
                </Button>
              )}
              <Button
                onClick={nextStep}
                disabled={!canProceed}
                loading={onboardingMutation.isPending}
              >
                {active === 1 ? "Finish" : "Continue"}
              </Button>
            </Group>
          )}

          {onboardingMutation.isError && (
            <Text c="red" size="sm" ta="center">
              {(onboardingMutation.error as Error).message}
            </Text>
          )}
        </Stack>
      </Container>
    </Center>
  );
}
