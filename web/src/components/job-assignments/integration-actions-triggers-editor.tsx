"use client";

import { useCallback, useMemo, useState } from "react";
import {
  Badge,
  Button,
  Group,
  Modal,
  MultiSelect,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import type { WorkspaceIntegrationItem } from "@/lib/workspace-integrations";
import {
  actionKey,
  groupSelectionByIntegration,
  integrationActionOptionsForAccount,
  isDirectDmSlug,
  keyToAction,
  mergeIntegrationGroup,
  pruneDirectDmRecipientsByKeys,
  PROVIDER_INBOUND_EVENTS,
  removeIntegrationGroup,
  systemActionOptions,
  type ActionableCatalogRow,
  type JobAssignmentActionDirectRecipient,
} from "@/lib/workspace-job-assignments";

function DirectDmRecipientsFields({
  title,
  rows,
  onChange,
}: {
  title: string;
  rows: JobAssignmentActionDirectRecipient[];
  onChange: (rows: JobAssignmentActionDirectRecipient[]) => void;
}) {
  const setRow = (i: number, patch: Partial<JobAssignmentActionDirectRecipient>) => {
    const next = rows.map((r, j) => (j === i ? { ...r, ...patch } : r));
    onChange(next);
  };
  const addRow = () => onChange([...rows, { external_thread_id: "", label: "" }]);
  const removeRow = (i: number) => onChange(rows.filter((_, j) => j !== i));

  return (
    <Stack gap="xs" mt="sm">
      <Text size="xs" fw={600}>
        {title}
      </Text>
      <Text size="xs" c="dimmed">
        Thread id is the provider conversation id (Telegram chat id, Instagram IGSID). Label is optional
        (shown to the agent).
      </Text>
      {rows.map((row, i) => (
        <Group key={i} align="flex-end" wrap="nowrap" grow>
          <TextInput
            label={i === 0 ? "Thread id" : undefined}
            placeholder="external_thread_id"
            value={row.external_thread_id}
            onChange={(e) => setRow(i, { external_thread_id: e.currentTarget.value })}
          />
          <TextInput
            label={i === 0 ? "Label (optional)" : undefined}
            placeholder="e.g. VIP lead"
            value={row.label ?? ""}
            onChange={(e) => setRow(i, { label: e.currentTarget.value })}
          />
          <Button size="xs" variant="light" color="red" onClick={() => removeRow(i)} disabled={rows.length <= 1}>
            Remove
          </Button>
        </Group>
      ))}
      <Button size="xs" variant="default" onClick={addRow}>
        Add recipient
      </Button>
    </Stack>
  );
}

type Props = {
  actionables: ActionableCatalogRow[];
  integrations: WorkspaceIntegrationItem[];
  actionKeys: string[];
  integrationEventSlugs: string[];
  directDmRecipientsByKey: Record<string, JobAssignmentActionDirectRecipient[]>;
  onActionKeysChange: (keys: string[]) => void;
  onIntegrationEventSlugsChange: (slugs: string[]) => void;
  onDirectDmRecipientsByKeyChange: (next: Record<string, JobAssignmentActionDirectRecipient[]>) => void;
};

type ModalDraft = {
  accountId: string;
  triggerSlugs: string[];
  actionKeysForAccount: string[];
  directDmRecipientsByKey: Record<string, JobAssignmentActionDirectRecipient[]>;
};

const EMPTY_DRAFT: ModalDraft = {
  accountId: "",
  triggerSlugs: [],
  actionKeysForAccount: [],
  directDmRecipientsByKey: {},
};

export function IntegrationActionsTriggersEditor({
  actionables,
  integrations,
  actionKeys,
  integrationEventSlugs,
  directDmRecipientsByKey,
  onActionKeysChange,
  onIntegrationEventSlugsChange,
  onDirectDmRecipientsByKeyChange,
}: Props) {
  const [opened, { open, close }] = useDisclosure(false);
  const [modalMode, setModalMode] = useState<"add" | "edit">("add");
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<ModalDraft>(EMPTY_DRAFT);

  const { attached, systemActionKeys } = useMemo(
    () => groupSelectionByIntegration(actionKeys, integrationEventSlugs, integrations),
    [actionKeys, integrationEventSlugs, integrations],
  );

  const attachedIds = useMemo(() => new Set(attached.map((a) => a.integration_account_id)), [attached]);

  const availableToAttach = useMemo(
    () => integrations.filter((i) => !attachedIds.has(i.id)),
    [integrations, attachedIds],
  );

  const openAdd = useCallback(() => {
    setModalMode("add");
    setStep(0);
    setDraft(EMPTY_DRAFT);
    open();
  }, [open]);

  const openEdit = useCallback(
    (integrationAccountId: string) => {
      const g = attached.find((x) => x.integration_account_id === integrationAccountId);
      if (!g) return;
      setModalMode("edit");
      setStep(1);
      setDraft({
        accountId: integrationAccountId,
        triggerSlugs: [...g.eventSlugs],
        actionKeysForAccount: [...g.actionKeys],
        directDmRecipientsByKey: (() => {
          const rec: Record<string, JobAssignmentActionDirectRecipient[]> = {};
          for (const k of g.actionKeys) {
            if (!isDirectDmSlug(keyToAction(k).actionable_slug)) continue;
            const existing = directDmRecipientsByKey[k];
            rec[k] =
              existing && existing.length > 0
                ? existing.map((x) => ({
                    external_thread_id: x.external_thread_id,
                    label: x.label ?? "",
                  }))
                : [{ external_thread_id: "", label: "" }];
          }
          return rec;
        })(),
      });
      open();
    },
    [attached, directDmRecipientsByKey, open],
  );

  const closeModal = useCallback(() => {
    close();
    setDraft(EMPTY_DRAFT);
    setStep(0);
  }, [close]);

  const selectedIntegration = useMemo(
    () => integrations.find((i) => i.id === draft.accountId) ?? null,
    [integrations, draft.accountId],
  );

  const provider = (selectedIntegration?.provider ?? "").toLowerCase();
  const triggerOptions =
    provider === "telegram" || provider === "instagram"
      ? [...PROVIDER_INBOUND_EVENTS[provider]]
      : [];

  const actionOptionsForDraft = useMemo(
    () => integrationActionOptionsForAccount(actionables, draft.accountId),
    [actionables, draft.accountId],
  );

  const attachSelectData = useMemo(
    () =>
      availableToAttach.map((i) => ({
        value: i.id,
        label: `${i.display_name} (${i.provider})`,
      })),
    [availableToAttach],
  );

  const confirmModal = useCallback(() => {
    if (!draft.accountId) return;
    const { actionKeys: nextKeys, eventSlugs: nextSlugs } = mergeIntegrationGroup(
      actionKeys,
      integrationEventSlugs,
      draft.accountId,
      draft.actionKeysForAccount,
      draft.triggerSlugs,
      integrations,
    );
    let nextRecipients = pruneDirectDmRecipientsByKeys(directDmRecipientsByKey, nextKeys);
    for (const [k, rows] of Object.entries(draft.directDmRecipientsByKey)) {
      if (draft.actionKeysForAccount.includes(k)) {
        nextRecipients = { ...nextRecipients, [k]: rows };
      }
    }
    onDirectDmRecipientsByKeyChange(nextRecipients);
    onActionKeysChange(nextKeys);
    onIntegrationEventSlugsChange(nextSlugs);
    closeModal();
  }, [
    actionKeys,
    integrationEventSlugs,
    draft,
    integrations,
    directDmRecipientsByKey,
    onActionKeysChange,
    onIntegrationEventSlugsChange,
    onDirectDmRecipientsByKeyChange,
    closeModal,
  ]);

  const removeCard = useCallback(
    (integrationAccountId: string) => {
      const { actionKeys: k, eventSlugs: s } = removeIntegrationGroup(
        actionKeys,
        integrationEventSlugs,
        integrationAccountId,
      );
      onDirectDmRecipientsByKeyChange(pruneDirectDmRecipientsByKeys(directDmRecipientsByKey, k));
      onActionKeysChange(k);
      onIntegrationEventSlugsChange(s);
    },
    [actionKeys, integrationEventSlugs, directDmRecipientsByKey, onActionKeysChange, onIntegrationEventSlugsChange, onDirectDmRecipientsByKeyChange],
  );

  const onSystemToolsChange = useCallback(
    (nextSystemKeys: string[]) => {
      const integrationKeys = actionKeys.filter((k) => keyToAction(k).integration_account_id != null);
      onActionKeysChange([...integrationKeys, ...nextSystemKeys]);
    },
    [actionKeys, onActionKeysChange],
  );

  const sysOptions = useMemo(() => systemActionOptions(actionables), [actionables]);

  const canGoNextFromStep0 = draft.accountId.length > 0;
  const canGoNextFromStep1 = draft.accountId.length > 0;
  const canConfirm = draft.actionKeysForAccount.length > 0;
  const minStep = modalMode === "add" ? 0 : 1;

  return (
    <Stack gap="md">
      <div>
        <Text size="sm" fw={600} mb={4}>
          Connected integrations
        </Text>
        <Text size="xs" c="dimmed" mb="sm">
          Configure triggers and actions per account. Use &quot;Attach integration&quot; to add another
          workspace account this job may use.
        </Text>
        <Stack gap="sm">
          {attached.map((g) => (
            <Paper key={g.integration_account_id} withBorder radius="md" p="md">
              <Group justify="space-between" align="flex-start" wrap="nowrap" mb="xs">
                <Group gap="xs">
                  <Badge variant="light">{g.provider}</Badge>
                  <Text fw={500}>{g.display_name}</Text>
                </Group>
                <Group gap="xs">
                  <Button size="xs" variant="light" onClick={() => openEdit(g.integration_account_id)}>
                    Edit
                  </Button>
                  <Button size="xs" variant="subtle" color="red" onClick={() => removeCard(g.integration_account_id)}>
                    Remove
                  </Button>
                </Group>
              </Group>
              <Text size="xs" c="dimmed" mb={4}>
                Triggers
              </Text>
              <Group gap={6} mb="sm">
                {g.eventSlugs.length ? (
                  g.eventSlugs.map((s) => (
                    <Badge key={s} size="sm" variant="outline">
                      {s}
                    </Badge>
                  ))
                ) : (
                  <Text size="xs" c="dimmed">
                    None (tools-only for this account)
                  </Text>
                )}
              </Group>
              <Text size="xs" c="dimmed" mb={4}>
                Actions
              </Text>
              <Group gap={6}>
                {g.actionKeys.map((k) => {
                  const row = actionables.find((a) => actionKey(a) === k);
                  return (
                    <Badge key={k} size="sm" variant="light">
                      {row?.name ?? k}
                    </Badge>
                  );
                })}
              </Group>
              {g.actionKeys
                .filter((k) => isDirectDmSlug(keyToAction(k).actionable_slug))
                .map((ak) => {
                  const row = actionables.find((a) => actionKey(a) === ak);
                  const title = `Recipients — ${row?.name ?? "direct DM"}`;
                  const rows =
                    directDmRecipientsByKey[ak] && directDmRecipientsByKey[ak].length > 0
                      ? directDmRecipientsByKey[ak]
                      : [{ external_thread_id: "", label: "" }];
                  return (
                    <DirectDmRecipientsFields
                      key={ak}
                      title={title}
                      rows={rows}
                      onChange={(next) =>
                        onDirectDmRecipientsByKeyChange({
                          ...directDmRecipientsByKey,
                          [ak]: next,
                        })
                      }
                    />
                  );
                })}
            </Paper>
          ))}
          <Button
            variant="default"
            style={{ borderStyle: "dashed" }}
            disabled={availableToAttach.length === 0}
            onClick={openAdd}
          >
            Attach integration
          </Button>
        </Stack>
      </div>

      <div>
        <Text size="sm" fw={600} mb={4}>
          System tools
        </Text>
        <Text size="xs" c="dimmed" mb="sm">
          Scheduling and web chat tools are not tied to a specific integration account.
        </Text>
        <MultiSelect
          placeholder="Optional system capabilities"
          data={sysOptions}
          value={systemActionKeys}
          onChange={onSystemToolsChange}
          searchable
        />
      </div>

      <Modal
        opened={opened}
        onClose={closeModal}
        title={modalMode === "add" ? "Attach integration" : "Edit integration"}
        centered
        size="md"
      >
        <Stack gap="md">
          {modalMode === "add" && step === 0 ? (
            <>
              <Text size="sm" c="dimmed">
                The AI will receive events from this account (when you add triggers) and may call actions
                you grant on this account.
              </Text>
              <Select
                label="Integration"
                placeholder="Choose a workspace account"
                data={attachSelectData}
                value={draft.accountId || null}
                onChange={(v) => setDraft((d) => ({ ...d, accountId: v ?? "" }))}
                searchable
              />
            </>
          ) : null}

          {step === 1 ? (
            <>
              <Text size="sm" c="dimmed">
                A trigger starts this job when the event fires; the agent then runs with the job&apos;s
                instructions and tools.
              </Text>
              <MultiSelect
                label="Inbound triggers for this account"
                description={`Provider: ${provider || "—"}`}
                data={triggerOptions}
                value={draft.triggerSlugs}
                onChange={(v) => setDraft((d) => ({ ...d, triggerSlugs: v }))}
                searchable
              />
            </>
          ) : null}

          {step === 2 ? (
            <>
              <Text size="sm" c="dimmed">
                Pick what this job may do on this account (e.g. send a DM). More capabilities appear here as
                the catalog grows.
              </Text>
              <MultiSelect
                label="Actions on this account"
                data={actionOptionsForDraft}
                value={draft.actionKeysForAccount}
                onChange={(v) =>
                  setDraft((d) => {
                    const nextKeys = v;
                    const rec = { ...d.directDmRecipientsByKey };
                    for (const key of nextKeys) {
                      if (isDirectDmSlug(keyToAction(key).actionable_slug) && !rec[key]) {
                        rec[key] = [{ external_thread_id: "", label: "" }];
                      }
                    }
                    for (const k of Object.keys(rec)) {
                      if (!nextKeys.includes(k)) delete rec[k];
                    }
                    return { ...d, actionKeysForAccount: nextKeys, directDmRecipientsByKey: rec };
                  })
                }
                searchable
              />
              {draft.actionKeysForAccount
                .filter((k) => isDirectDmSlug(keyToAction(k).actionable_slug))
                .map((ak) => {
                  const row = actionables.find((a) => actionKey(a) === ak);
                  const title = `Recipients — ${row?.name ?? "direct DM"}`;
                  const rows = draft.directDmRecipientsByKey[ak] ?? [{ external_thread_id: "", label: "" }];
                  return (
                    <DirectDmRecipientsFields
                      key={ak}
                      title={title}
                      rows={rows}
                      onChange={(next) =>
                        setDraft((d) => ({
                          ...d,
                          directDmRecipientsByKey: { ...d.directDmRecipientsByKey, [ak]: next },
                        }))
                      }
                    />
                  );
                })}
            </>
          ) : null}

          <Group justify="space-between">
            <Button variant="default" onClick={closeModal}>
              Cancel
            </Button>
            <Group gap="xs">
              {step > minStep ? (
                <Button variant="default" onClick={() => setStep((s) => s - 1)}>
                  Back
                </Button>
              ) : null}
              {modalMode === "add" && step === 0 ? (
                <Button disabled={!canGoNextFromStep0} onClick={() => setStep(1)}>
                  Next
                </Button>
              ) : null}
              {step === 1 ? (
                <Button onClick={() => setStep(2)} disabled={!canGoNextFromStep1}>
                  Next
                </Button>
              ) : null}
              {step === 2 ? (
                <Button onClick={confirmModal} disabled={!canConfirm}>
                  Save
                </Button>
              ) : null}
            </Group>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
