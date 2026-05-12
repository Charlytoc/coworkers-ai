import { apiFetch, apiReadJson, throwApiError } from "@/lib/api-request";
import type { CyberIdentity } from "@/lib/workspace-cyber-identities";
import type { WorkspaceIntegrationItem } from "@/lib/workspace-integrations";

export type ActionableCatalogRow = {
  slug: string;
  name: string;
  description: string;
  provider: string;
  integration_account_id: string | null;
  integration: {
    integration_account_id: string;
    provider: string;
    display_name: string;
    status: string;
  } | null;
};

export type JobAssignmentConfigAccount = {
  id: string;
  provider: string;
};

export type JobAssignmentConfigIdentity = {
  id: string;
  type: string;
  config: Record<string, unknown>;
};

/** Canonical ``JobAssignment.config`` from the API (after create/update). */
export type JobAssignmentConfig = {
  accounts: JobAssignmentConfigAccount[];
  identities: JobAssignmentConfigIdentity[];
  triggers: Record<string, unknown>[];
  actions: Record<string, unknown>[];
  approval_policy?: Record<string, unknown> | null;
  output_schema?: Record<string, unknown> | null;
};

export type JobAssignment = {
  id: string;
  workspace_id: number;
  role_name: string;
  description: string;
  instructions: string;
  enabled: boolean;
  config: JobAssignmentConfig;
  created: string;
};

export type JobAssignmentActionDirectRecipient = {
  external_thread_id: string;
  label?: string | null;
};

export const REPLY_DM_SLUGS = ["telegram.reply_dm", "instagram.reply_dm"] as const;

export const DIRECT_DM_SLUGS = ["telegram.send_direct_dm", "instagram.send_direct_dm"] as const;

export function isReplyDmSlug(slug: string): boolean {
  return (REPLY_DM_SLUGS as readonly string[]).includes(slug);
}

export function isDirectDmSlug(slug: string): boolean {
  return (DIRECT_DM_SLUGS as readonly string[]).includes(slug);
}

export function pruneDirectDmRecipientsByKeys(
  map: Record<string, JobAssignmentActionDirectRecipient[]>,
  actionKeys: string[],
): Record<string, JobAssignmentActionDirectRecipient[]> {
  const allowed = new Set(actionKeys);
  const next: Record<string, JobAssignmentActionDirectRecipient[]> = {};
  for (const [k, rows] of Object.entries(map)) {
    if (allowed.has(k)) next[k] = rows;
  }
  return next;
}

export function parseActionsFromConfig(actions: Record<string, unknown>[]): {
  actionKeys: string[];
  directDmRecipientsByKey: Record<string, JobAssignmentActionDirectRecipient[]>;
} {
  const actionKeys: string[] = [];
  const directDmRecipientsByKey: Record<string, JobAssignmentActionDirectRecipient[]> = {};
  for (const raw of actions) {
    const slug = String((raw as { actionable_slug?: string }).actionable_slug ?? "");
    const acc = (raw as { integration_account_id?: string | null }).integration_account_id;
    const key = `${slug}::${acc ?? ""}`;
    actionKeys.push(key);
    const drm = (raw as { direct_dm_recipients?: unknown }).direct_dm_recipients;
    if (!Array.isArray(drm) || drm.length === 0) continue;
    const rows: JobAssignmentActionDirectRecipient[] = [];
    for (const r of drm) {
      if (!r || typeof r !== "object") continue;
      const ob = r as Record<string, unknown>;
      const tid = String(ob.external_thread_id ?? "").trim();
      if (!tid) continue;
      const labelRaw = ob.label;
      const label =
        typeof labelRaw === "string" && labelRaw.trim() ? labelRaw.trim() : null;
      rows.push({ external_thread_id: tid, label });
    }
    if (rows.length) directDmRecipientsByKey[key] = rows;
  }
  return { actionKeys, directDmRecipientsByKey };
}

export type JobAssignmentCreateInput = {
  role_name: string;
  description?: string;
  instructions?: string;
  enabled?: boolean;
  /** Partial config is merged with server defaults and coerced to ``JobAssignmentConfig``. */
  config?: Partial<JobAssignmentConfig> & Record<string, unknown>;
};

export type JobAssignmentUpdateInput = Partial<JobAssignmentCreateInput>;

/** Catalog row key: ``slug::<integration_account_id>`` (empty suffix when id is null). */
export function actionKey(row: ActionableCatalogRow): string {
  const id = row.integration_account_id;
  return `${row.slug}::${id ?? ""}`;
}

/** Reverse of :func:`actionKey` for PATCH payloads. */
export function keyToAction(key: string): { actionable_slug: string; integration_account_id: string | null } {
  const idx = key.indexOf("::");
  if (idx === -1) return { actionable_slug: key, integration_account_id: null };
  const slug = key.slice(0, idx);
  const rest = key.slice(idx + 2);
  return { actionable_slug: slug, integration_account_id: rest || null };
}

export function directDmRecipientsValidationError(
  actionKeys: string[],
  directDmRecipientsByKey: Record<string, JobAssignmentActionDirectRecipient[]>,
): string | null {
  for (const key of actionKeys) {
    const { actionable_slug } = keyToAction(key);
    if (!isDirectDmSlug(actionable_slug)) continue;
    const cleaned = (directDmRecipientsByKey[key] ?? []).filter((r) =>
      (r.external_thread_id ?? "").trim(),
    );
    if (cleaned.length === 0) {
      return `Action "${actionable_slug}" needs at least one direct DM recipient with a non-empty thread id.`;
    }
  }
  return null;
}

export function buildIdentitiesPayload(
  selectedIdentityIds: string[],
  identities: CyberIdentity[],
): JobAssignmentConfigIdentity[] {
  return selectedIdentityIds
    .map((id) => identities.find((i) => i.id === id))
    .filter((row): row is CyberIdentity => Boolean(row))
    .map((i) => ({ id: i.id, type: i.type, config: i.config ?? {} }));
}

export function buildActionsPayload(
  selectedActionKeys: string[],
  directDmRecipientsByKey: Record<string, JobAssignmentActionDirectRecipient[]> = {},
): Record<string, unknown>[] {
  return selectedActionKeys.map((key) => {
    const { actionable_slug, integration_account_id } = keyToAction(key);
    const row: Record<string, unknown> = { actionable_slug };
    if (integration_account_id) {
      row.integration_account_id = integration_account_id;
    }
    const rec = directDmRecipientsByKey[key]?.filter((r) => (r.external_thread_id ?? "").trim()) ?? [];
    if (rec.length) {
      row.direct_dm_recipients = rec.map((r) => {
        const tid = (r.external_thread_id ?? "").trim();
        const label = (r.label ?? "").trim();
        return label ? { external_thread_id: tid, label } : { external_thread_id: tid };
      });
    }
    return row;
  });
}

/** Inbound events that map to at most one enabled listener per integration account. */
export const INTEGRATION_INBOUND_EVENT_SLUGS = [
  "telegram.private_message",
  "instagram.dm_message",
] as const;

const INBOUND_SLUG_SET = new Set<string>(INTEGRATION_INBOUND_EVENT_SLUGS);

export const INTEGRATION_INBOUND_EVENT_OPTIONS = [
  { value: "telegram.private_message", label: "Telegram — inbound private messages" },
  { value: "instagram.dm_message", label: "Instagram — inbound direct messages" },
] as const;

/** Inbound event options shown per provider when attaching/editing an integration. */
export const PROVIDER_INBOUND_EVENTS: Record<
  "telegram" | "instagram",
  readonly { value: string; label: string }[]
> = {
  telegram: INTEGRATION_INBOUND_EVENT_OPTIONS.filter((o) => o.value.startsWith("telegram.")),
  instagram: INTEGRATION_INBOUND_EVENT_OPTIONS.filter((o) => o.value.startsWith("instagram.")),
};

export type AttachedIntegrationGroup = {
  integration_account_id: string;
  provider: string;
  display_name: string;
  actionKeys: string[];
  /** Subset of ``integrationEventSlugs`` that apply to this provider (for display). */
  eventSlugs: string[];
};

export function groupSelectionByIntegration(
  actionKeys: string[],
  integrationEventSlugs: string[],
  integrations: WorkspaceIntegrationItem[],
): { attached: AttachedIntegrationGroup[]; systemActionKeys: string[] } {
  const systemActionKeys: string[] = [];
  const byAccount = new Map<string, string[]>();

  for (const key of actionKeys) {
    const { integration_account_id } = keyToAction(key);
    if (!integration_account_id) {
      systemActionKeys.push(key);
      continue;
    }
    if (!byAccount.has(integration_account_id)) {
      byAccount.set(integration_account_id, []);
    }
    byAccount.get(integration_account_id)!.push(key);
  }

  const integrationById = new Map(integrations.map((i) => [i.id, i] as const));

  const attached: AttachedIntegrationGroup[] = [];
  for (const [accountId, keys] of byAccount) {
    const row = integrationById.get(accountId);
    const provider = (row?.provider ?? "unknown").toLowerCase();
    const inboundOpts =
      provider === "telegram" || provider === "instagram"
        ? PROVIDER_INBOUND_EVENTS[provider]
        : [];
    const allowed = new Set(inboundOpts.map((o) => o.value));
    const eventSlugs = integrationEventSlugs.filter((s) => allowed.has(s));
    attached.push({
      integration_account_id: accountId,
      provider,
      display_name: row?.display_name ?? accountId,
      actionKeys: keys,
      eventSlugs,
    });
  }
  attached.sort((a, b) => a.display_name.localeCompare(b.display_name));
  return { attached, systemActionKeys };
}

/** Actionable rows not bound to an integration (system tools). */
export function systemActionableRows(actionables: ActionableCatalogRow[]): ActionableCatalogRow[] {
  return actionables.filter((a) => a.integration_account_id == null);
}

export function systemActionOptions(actionables: ActionableCatalogRow[]) {
  return systemActionableRows(actionables).map((a) => ({
    value: actionKey(a),
    label: a.name,
  }));
}

export function integrationActionOptionsForAccount(
  actionables: ActionableCatalogRow[],
  integrationAccountId: string,
) {
  return actionables
    .filter((a) => a.integration_account_id === integrationAccountId)
    .map((a) => ({
      value: actionKey(a),
      label: a.name,
    }));
}

/** Remove one integration’s actions and prune inbound slugs if no send actions remain for that provider. */
export function removeIntegrationGroup(
  actionKeys: string[],
  integrationEventSlugs: string[],
  integrationAccountId: string,
): { actionKeys: string[]; eventSlugs: string[] } {
  const newKeys = actionKeys.filter(
    (k) => keyToAction(k).integration_account_id !== integrationAccountId,
  );
  const hasTelegramSend = newKeys.some((k) => {
    const a = keyToAction(k);
    return a.actionable_slug === "telegram.reply_dm" && a.integration_account_id != null;
  });
  const hasInstagramSend = newKeys.some((k) => {
    const a = keyToAction(k);
    return a.actionable_slug === "instagram.reply_dm" && a.integration_account_id != null;
  });
  let eventSlugs = [...integrationEventSlugs];
  if (!hasTelegramSend) {
    eventSlugs = eventSlugs.filter((s) => s !== "telegram.private_message");
  }
  if (!hasInstagramSend) {
    eventSlugs = eventSlugs.filter((s) => s !== "instagram.dm_message");
  }
  return { actionKeys: newKeys, eventSlugs };
}

/** Replace or add actions for ``integrationAccountId`` and set inbound slugs for that account's provider. */
export function mergeIntegrationGroup(
  actionKeys: string[],
  integrationEventSlugs: string[],
  integrationAccountId: string,
  newActionKeysForAccount: string[],
  newEventSlugsForModal: string[],
  integrations: WorkspaceIntegrationItem[],
): { actionKeys: string[]; eventSlugs: string[] } {
  const without = actionKeys.filter(
    (k) => keyToAction(k).integration_account_id !== integrationAccountId,
  );
  const mergedKeys = [...without, ...newActionKeysForAccount];
  const row = integrations.find((i) => i.id === integrationAccountId);
  const provider = (row?.provider ?? "").toLowerCase();
  let nextSlugs: string[];
  if (provider === "telegram" || provider === "instagram") {
    const providerSlugSet = new Set(PROVIDER_INBOUND_EVENTS[provider].map((o) => o.value));
    const allowedModal = newEventSlugsForModal.filter((s) => providerSlugSet.has(s));
    const stripped = integrationEventSlugs.filter((s) => !providerSlugSet.has(s));
    nextSlugs = [...stripped, ...allowedModal];
  } else {
    const slugSet = new Set(integrationEventSlugs);
    for (const s of newEventSlugsForModal) {
      slugSet.add(s);
    }
    nextSlugs = [...slugSet];
  }
  return { actionKeys: mergedKeys, eventSlugs: [...new Set(nextSlugs)] };
}

export type TriggerRecord = Record<string, unknown>;

/** Split known inbound integration event triggers from cron / other triggers (preserved on save). */
export function splitJobTriggers(triggers: TriggerRecord[] | undefined): {
  integrationEventSlugs: string[];
  otherTriggers: TriggerRecord[];
} {
  const list = triggers ?? [];
  const seenInbound = new Set<string>();
  const otherTriggers: TriggerRecord[] = [];
  for (const t of list) {
    const ty = typeof t.type === "string" ? t.type : "";
    const on = typeof (t as { on?: string }).on === "string" ? (t as { on: string }).on : "";
    if (ty === "event" && INBOUND_SLUG_SET.has(on)) {
      seenInbound.add(on);
    } else {
      otherTriggers.push(t);
    }
  }
  const integrationEventSlugs = INTEGRATION_INBOUND_EVENT_SLUGS.filter((s) => seenInbound.has(s));
  return { integrationEventSlugs, otherTriggers };
}

export function buildTriggersPayload(
  integrationEventSlugs: string[],
  otherTriggers: TriggerRecord[],
): TriggerRecord[] {
  const events = integrationEventSlugs.map((on) => ({ type: "event", on, filter: {} }));
  return [...events, ...otherTriggers];
}

/** Build MultiSelect keys from persisted ``config.actions`` (no per-action extras). */
export function actionsToKeys(actions: Record<string, unknown>[]): string[] {
  return parseActionsFromConfig(actions).actionKeys;
}

export async function fetchWorkspaceActionables(
  token: string,
  organizationId: string,
  workspaceId: number,
): Promise<ActionableCatalogRow[]> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/actionables/`,
    token,
    organizationId,
  );
  return apiReadJson<ActionableCatalogRow[]>(response, "Failed to load actionables");
}

export async function fetchJobAssignments(
  token: string,
  organizationId: string,
  workspaceId: number,
): Promise<JobAssignment[]> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/job-assignments/`,
    token,
    organizationId,
  );
  return apiReadJson<JobAssignment[]>(response, "Failed to load job assignments");
}

export async function fetchJobAssignment(
  token: string,
  organizationId: string,
  workspaceId: number,
  jobAssignmentId: string,
): Promise<JobAssignment> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/job-assignments/${jobAssignmentId}/`,
    token,
    organizationId,
  );
  return apiReadJson<JobAssignment>(response, "Failed to load job assignment");
}

export async function createJobAssignment(
  token: string,
  organizationId: string,
  workspaceId: number,
  input: JobAssignmentCreateInput,
): Promise<JobAssignment> {
  const response = await apiFetch(`/workspaces/${workspaceId}/job-assignments/`, token, organizationId, {
    method: "POST",
    jsonBody: input,
  });
  return apiReadJson<JobAssignment>(response, "Failed to create job assignment");
}

export async function updateJobAssignment(
  token: string,
  organizationId: string,
  workspaceId: number,
  jobAssignmentId: string,
  input: JobAssignmentUpdateInput,
): Promise<JobAssignment> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/job-assignments/${jobAssignmentId}/`,
    token,
    organizationId,
    {
      method: "PATCH",
      jsonBody: input,
    },
  );
  return apiReadJson<JobAssignment>(response, "Failed to update job assignment");
}

export async function deleteJobAssignment(
  token: string,
  organizationId: string,
  workspaceId: number,
  jobAssignmentId: string,
): Promise<void> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/job-assignments/${jobAssignmentId}/`,
    token,
    organizationId,
    {
      method: "DELETE",
    },
  );
  if (!response.ok && response.status !== 204) {
    await throwApiError(response, "Failed to delete job assignment");
  }
}
