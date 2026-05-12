"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ActionIcon,
  AppShell,
  Box,
  Burger,
  Button,
  Center,
  Group,
  Loader,
  NavLink,
  Text,
  Title,
} from "@mantine/core";
import { useDisclosure, useLocalStorage } from "@mantine/hooks";
import { OrganizationSwitcher } from "@/components/OrganizationSwitcher";
import { WorkspaceSwitcher } from "@/components/WorkspaceSwitcher";
import {
  SELECTED_ORG_ID_KEY,
  SELECTED_WORKSPACE_ID_KEY,
  TOKEN_KEY,
  USER_KEY,
  readStoredAuth,
  type AuthUser,
} from "@/lib/auth-storage";

export function AppShellLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [mounted, setMounted] = useState(false);
  const [user, , removeUser] = useLocalStorage<AuthUser | null>({
    key: USER_KEY,
    defaultValue: null,
    getInitialValueInEffect: true,
  });
  const [, , removeToken] = useLocalStorage<string | null>({
    key: TOKEN_KEY,
    defaultValue: null,
    getInitialValueInEffect: true,
  });
  const [, , removeSelectedOrg] = useLocalStorage<string | null>({
    key: SELECTED_ORG_ID_KEY,
    defaultValue: null,
    getInitialValueInEffect: true,
  });
  const [selectedWorkspaceId, , removeSelectedWorkspace] = useLocalStorage<number | null>({
    key: SELECTED_WORKSPACE_ID_KEY,
    defaultValue: null,
    getInitialValueInEffect: true,
  });

  const [mobileNavOpened, { toggle: toggleMobileNav, close: closeMobileNav }] = useDisclosure();
  const [desktopNavOpened, { toggle: toggleDesktopNav }] = useDisclosure(true);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    closeMobileNav();
  }, [pathname, closeMobileNav]);

  useEffect(() => {
    if (!mounted) return;
    const onDashboard = pathname === "/dashboard" || pathname?.startsWith("/dashboard/");
    if (!onDashboard) return;
    if (!readStoredAuth().user) {
      router.replace("/chat");
    }
  }, [mounted, pathname, router]);

  if (!mounted) {
    const onChat = pathname === "/chat" || pathname?.startsWith("/chat/");
    if (onChat) {
      return <>{children}</>;
    }
    return (
      <Center h="100vh" bg="var(--mantine-color-body)">
        <Loader size="sm" />
      </Center>
    );
  }

  const sessionUser = readStoredAuth().user;
  const effectiveUser = user ?? sessionUser;

  if (!effectiveUser) {
    return <>{children}</>;
  }

  function signOut() {
    removeToken();
    removeUser();
    removeSelectedOrg();
    removeSelectedWorkspace();
    router.push("/");
  }

  const workspaceNavPrefix =
    selectedWorkspaceId != null && !Number.isNaN(selectedWorkspaceId)
      ? `/workspaces/${selectedWorkspaceId}`
      : null;

  function workspaceSectionActive(segment: string): boolean {
    if (!workspaceNavPrefix || !pathname) return false;
    const base = `${workspaceNavPrefix}/${segment}`;
    return pathname === base || pathname.startsWith(`${base}/`);
  }

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{
        width: 220,
        breakpoint: "sm",
        collapsed: { mobile: !mobileNavOpened, desktop: !desktopNavOpened },
      }}
      padding={0}
    >
      <AppShell.Header px="md" py={6} style={{ display: "flex", alignItems: "center" }}>
        <Group justify="space-between" w="100%" wrap="nowrap" gap="sm">
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
            <Burger
              opened={mobileNavOpened}
              onClick={toggleMobileNav}
              hiddenFrom="sm"
              size="sm"
              aria-label="Open navigation"
            />
            <ActionIcon
              variant="default"
              size="lg"
              visibleFrom="sm"
              onClick={toggleDesktopNav}
              aria-label={desktopNavOpened ? "Hide sidebar" : "Show sidebar"}
              title={desktopNavOpened ? "Hide sidebar" : "Show sidebar"}
            >
              <Text fw={700} lh={1} fz="md" style={{ fontFamily: "monospace" }}>
                {desktopNavOpened ? "⟨" : "⟩"}
              </Text>
            </ActionIcon>
            <Title order={4} fw={700} lineClamp={1} style={{ minWidth: 0 }}>
              Coworkers AI
            </Title>
          </Group>
          <Group gap="sm" wrap="nowrap" justify="flex-end" style={{ flexShrink: 0 }}>
            <Box visibleFrom="sm" maw={240} miw={0} style={{ flex: "0 1 auto" }}>
              <OrganizationSwitcher />
            </Box>
            <Text size="sm" c="dimmed" visibleFrom="md" lineClamp={1} maw={200}>
              {effectiveUser.email}
            </Text>
            <Button variant="default" size="xs" onClick={signOut}>
              <Text visibleFrom="sm">Sign out</Text>
              <Text hiddenFrom="sm" size="xs">
                Out
              </Text>
            </Button>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        <Box hiddenFrom="sm" mb="md">
          <OrganizationSwitcher />
        </Box>
        <NavLink
          component={Link}
          href="/dashboard"
          label="Dashboard"
          active={pathname === "/dashboard"}
          onClick={() => closeMobileNav()}
        />
        <NavLink
          component={Link}
          href="/chat"
          label="Chat"
          active={pathname === "/chat"}
          onClick={() => closeMobileNav()}
        />
        <NavLink
          component={Link}
          href="/settings"
          label="Settings"
          active={pathname === "/settings" || pathname?.startsWith("/settings/")}
          onClick={() => closeMobileNav()}
        />
        <Text size="xs" fw={700} c="dimmed" tt="uppercase" mt="md" mb={4} px="xs">
          Workspace
        </Text>
        <Box mb="xs">
          <WorkspaceSwitcher />
        </Box>
        <NavLink
          component={Link}
          href="/workspace"
          label="Workspace home"
          active={pathname === "/workspace" || Boolean(pathname?.startsWith("/workspace/"))}
          onClick={() => closeMobileNav()}
        />
        {workspaceNavPrefix ? (
          <>
            <Text size="xs" fw={700} c="dimmed" tt="uppercase" mt="md" mb={4} px="xs">
              In this workspace
            </Text>
            <NavLink
              component={Link}
              href={`${workspaceNavPrefix}/cyber-identities`}
              label="Cyber identities"
              active={workspaceSectionActive("cyber-identities")}
              onClick={() => closeMobileNav()}
            />
            <NavLink
              component={Link}
              href={`${workspaceNavPrefix}/job-assignments`}
              label="Jobs"
              active={workspaceSectionActive("job-assignments")}
              onClick={() => closeMobileNav()}
            />
            <NavLink
              component={Link}
              href={`${workspaceNavPrefix}/integrations`}
              label="Accounts"
              active={workspaceSectionActive("integrations")}
              onClick={() => closeMobileNav()}
            />
            <NavLink
              component={Link}
              href={`${workspaceNavPrefix}/connect-integration`}
              label="Connect account"
              active={workspaceSectionActive("connect-integration")}
              onClick={() => closeMobileNav()}
            />
            <NavLink
              component={Link}
              href={`${workspaceNavPrefix}/artifacts`}
              label="Artifacts"
              active={workspaceSectionActive("artifacts")}
              onClick={() => closeMobileNav()}
            />
          </>
        ) : null}
      </AppShell.Navbar>

      <AppShell.Main
        bg="var(--mantine-color-body)"
        style={{
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          height: "calc(100vh - var(--app-shell-header-height, 56px))",
        }}
      >
        <Box style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          {children}
        </Box>
      </AppShell.Main>
    </AppShell>
  );
}
