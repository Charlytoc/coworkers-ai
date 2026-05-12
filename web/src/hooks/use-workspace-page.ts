"use client";

import { startTransition, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useLocalStorage } from "@mantine/hooks";
import {
  SELECTED_ORG_ID_KEY,
  SELECTED_WORKSPACE_ID_KEY,
  TOKEN_KEY,
  USER_KEY,
  readStoredAuth,
  type AuthUser,
} from "@/lib/auth-storage";
import { fetchWorkspaces, type WorkspaceResponse } from "@/lib/my-workspaces";

export function parseWorkspaceRouteId(param: string | string[] | undefined): number {
  const raw = typeof param === "string" ? param : Array.isArray(param) ? (param[0] ?? "") : "";
  return Number.parseInt(raw, 10);
}

export function useWorkspacePage() {
  const router = useRouter();
  const params = useParams();
  const workspaceId = parseWorkspaceRouteId(params.id);
  const [sessionOk, setSessionOk] = useState(false);
  const [user] = useLocalStorage<AuthUser | null>({
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
    const { user: stored } = readStoredAuth();
    if (!stored) {
      router.replace("/chat");
      return;
    }
    startTransition(() => {
      setSessionOk(true);
    });
  }, [router]);

  const orgId = selectedOrgId != null ? String(selectedOrgId) : null;
  const displayUser = user ?? readStoredAuth().user;

  const { data: workspaces, isPending: workspacesPending } = useQuery({
    queryKey: ["workspaces", token, orgId],
    queryFn: () => fetchWorkspaces(token!, orgId!),
    enabled: Boolean(token) && sessionOk && orgId != null,
    staleTime: 30_000,
  });

  const workspace = useMemo((): WorkspaceResponse | null => {
    if (!workspaces?.length || Number.isNaN(workspaceId)) return null;
    return workspaces.find((w) => w.id === workspaceId) ?? null;
  }, [workspaces, workspaceId]);

  const workspaceMismatch =
    selectedWorkspaceId != null && selectedWorkspaceId !== workspaceId && !Number.isNaN(workspaceId);

  const workspaceReady =
    Boolean(token) && sessionOk && orgId != null && !Number.isNaN(workspaceId) && Boolean(workspace);

  return {
    router,
    params,
    workspaceId,
    sessionOk,
    user,
    token,
    orgId,
    selectedWorkspaceId,
    displayUser,
    workspace,
    workspaces,
    workspacesPending,
    workspaceMismatch,
    workspaceReady,
  };
}
