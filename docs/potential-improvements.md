# Potential improvements

Backlog of improvements discussed but intentionally deferred. Each entry says what it is, why it matters, and where the change would land.

## Instagram

### Let the agent see past post images (visual context for ideation)

`instagram_insights` → `list_media` fetches `id, caption, media_type, timestamp, permalink, like_count, comments_count` but not `media_url` / `thumbnail_url`. The agent therefore reasons about past content from captions and metrics only — it cannot look at the visual style of previous posts when proposing or generating new ones.

- Add `media_url,thumbnail_url` to `_MEDIA_FIELDS` in `django/core/services/instagram_graph_api.py`.
- To actually use them, the agent loop would need image inputs (vision) for those URLs, e.g. a tool that downloads a media URL and attaches it to the conversation as an image.

### Expose media pagination in the `instagram_insights` tool

`list_media()` in `django/core/services/instagram_graph_api.py` already supports an `after` cursor, but the `instagram_insights` tool (`django/core/agent/tools/instagram_insights.py`) does not expose it, so the agent is capped at the 50 most recent posts. Add an optional `after` parameter to the tool and return the `paging.cursors.after` value in the tool output so the agent can walk further back in the account history.

### Enforce uniform aspect ratio for carousel slides server-side

Instagram crops every carousel slide to the first slide's aspect ratio. Prompt guidance tells the agent to use the same `size` for all slides, but there is no hard check. `_publish_instagram_post` in `django/core/agent/tools/publish_external_resource.py` could reject mixed image dimensions before hitting the Graph API.

## Agent tools

### `list_artifacts` tool for browsing existing artifacts

No agent tool lists or searches existing artifacts — the agent only knows the IDs of artifacts it created in the current run (tool responses) or those summarized in the artifact-creator completion callback. It cannot discover artifacts from past task executions (e.g. "reuse that image we generated last week", "find yesterday's caption draft"). The REST router `django/core/routers/workspace_artifacts.py` already lists artifacts for the frontend; a `list_artifacts` agent tool in `django/core/agent/tools/` with filters (kind, label, date, task execution/conversation) would close the gap.

## Django admin

### Stronger cross-record linking

Related records in the admin (`django/core/admin/`) are not linked to each other, so navigating a flow means copying IDs between changelists. Add clickable links between related objects, e.g.:

- `TaskExecution` → its `AgentSessionLog` runs (and back), so a task's agent executions are one click away.
- `TaskExecution` → child tasks spawned via `call_artifact_creator`, and → the `Artifact`s it produced.
- `JobAssignment` → its `TaskExecution` history; `Artifact` → its `MediaObject` / `IntegrationAccount`.

Implementation: `format_html` link columns in `list_display` and readonly link fields on detail pages (or inlines where the cardinality is small).

## Agent loop

### Deliver (or handle) the agent's final plain-text response

The agent loop captures the model's last assistant text as `final_response` (`django/core/agent/base.py`) and persists it in the task outputs (`task_execution_runner_persist.py`), but it is never sent to the user — only `send_message` / `send_direct_message` tool calls are delivered. The system prompt warns about this, yet the model still sometimes puts a small conclusion or user-visible answer in its final text, which then silently disappears. Options: auto-forward a non-empty `final_response` to the conversation's reply target when no send tool was called in the run; or surface it in the chat UI as a distinct "agent note"; at minimum, flag runs where `final_response` is non-empty but nothing was sent, to measure how often it happens.

## Publishing safety

### Wire up the approval gate before publishing

`TaskExecution.requires_approval`, `Status.WAITING_APPROVAL`, and `JobAssignmentConfig.approval_policy` all exist but nothing sets or enforces them — every creation site hardcodes `requires_approval=False`, so a job with publish rights posts to Instagram fully autonomously. Implement a human-in-the-loop checkpoint (UI + router action to approve/reject a pending task) before the agent calls `publish_external_resource`.
