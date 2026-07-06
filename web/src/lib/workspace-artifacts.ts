import type { components } from "@/lib/api/schema";
import { apiFetch, apiReadJson, throwApiError } from "@/lib/api-request";

export const ARTIFACT_KIND_OPTIONS = [
  { value: "text", label: "Text" },
  { value: "image", label: "Image" },
  { value: "video", label: "Video" },
  { value: "audio", label: "Audio" },
  { value: "document", label: "Document" },
  { value: "external_resource", label: "External resource" },
] as const;

export type ArtifactKind = (typeof ARTIFACT_KIND_OPTIONS)[number]["value"];

export type WorkspaceArtifact = components["schemas"]["ArtifactOut"];

export function artifactTitle(row: WorkspaceArtifact): string {
  if (row.label.trim()) return row.label;
  if (row.media?.display_name) return row.media.display_name;
  if (typeof row.metadata.title === "string" && row.metadata.title.trim()) {
    return row.metadata.title;
  }
  return `${row.kind} artifact`;
}

export function artifactTextBody(row: WorkspaceArtifact): string | null {
  if (row.kind === "external_resource") {
    const caption = row.metadata.caption;
    if (typeof caption === "string" && caption.trim()) return caption.trim();
    return null;
  }
  const text = row.metadata.text;
  if (typeof text === "string" && text.trim()) return text.trim();
  const summary = row.metadata.summary;
  if (typeof summary === "string" && summary.trim()) return summary.trim();
  return null;
}

function isHttpUrl(value: string): boolean {
  return value.startsWith("http://") || value.startsWith("https://");
}

function externalResourceAttachmentImageUrl(metadata: WorkspaceArtifact["metadata"]): string | null {
  const raw = metadata.attachments;
  if (!Array.isArray(raw)) return null;
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const att = item as Record<string, unknown>;
    if (att.kind !== "image" && att.type !== "image") continue;
    const media = att.media;
    if (!media || typeof media !== "object") continue;
    const url = (media as Record<string, unknown>).public_url;
    if (typeof url === "string" && url.trim() && isHttpUrl(url.trim())) return url.trim();
  }
  return null;
}

export function artifactPreviewImageUrl(row: WorkspaceArtifact): string | null {
  if (
    row.media?.public_url &&
    (row.kind === "image" || row.media.mime_type.startsWith("image/"))
  ) {
    return row.media.public_url;
  }
  if (row.kind === "external_resource") {
    return externalResourceAttachmentImageUrl(row.metadata);
  }
  return null;
}

export function isHtmlTextArtifact(row: WorkspaceArtifact): boolean {
  const extension = row.metadata.extension;
  return (
    row.kind === "text" &&
    typeof extension === "string" &&
    ["html", "htm"].includes(extension.toLowerCase())
  );
}

export function isImageArtifact(row: WorkspaceArtifact): boolean {
  return Boolean(
    row.media?.public_url &&
      (row.kind === "image" || row.media.mime_type.startsWith("image/")),
  );
}

export function formatArtifactBytes(value: number | null): string {
  if (value == null) return "";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export type WorkspaceArtifactFilters = {
  identityId?: string | null;
  jobAssignmentId?: string | null;
  integrationAccountId?: string | null;
  kind?: ArtifactKind | null;
  limit?: number;
};

export async function fetchWorkspaceArtifacts(
  token: string,
  organizationId: string,
  workspaceId: number,
  filters: WorkspaceArtifactFilters = {},
): Promise<WorkspaceArtifact[]> {
  const params = new URLSearchParams();
  if (filters.identityId) params.set("identity_id", filters.identityId);
  if (filters.jobAssignmentId) params.set("job_assignment_id", filters.jobAssignmentId);
  if (filters.integrationAccountId) {
    params.set("integration_account_id", filters.integrationAccountId);
  }
  if (filters.kind) params.set("kind", filters.kind);
  params.set("limit", String(filters.limit ?? 100));

  const response = await apiFetch(
    `/workspaces/${workspaceId}/artifacts/?${params.toString()}`,
    token,
    organizationId,
  );
  return apiReadJson<WorkspaceArtifact[]>(response, "Failed to load artifacts");
}

export async function deleteWorkspaceArtifact(
  token: string,
  organizationId: string,
  workspaceId: number,
  artifactId: string,
): Promise<void> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/artifacts/${artifactId}/`,
    token,
    organizationId,
    {
      method: "DELETE",
    },
  );
  if (!response.ok) await throwApiError(response, "Failed to delete artifact");
}

export async function fetchWorkspaceArtifact(
  token: string,
  organizationId: string,
  workspaceId: number,
  artifactId: string,
): Promise<WorkspaceArtifact> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/artifacts/${artifactId}/`,
    token,
    organizationId,
  );
  return apiReadJson<WorkspaceArtifact>(response, "Failed to load artifact");
}

export type InstagramArtifactComment = {
  id: string;
  text: string;
  username: string;
  timestamp: string | null;
};

export type InstagramArtifactCommentsResponse = {
  media_id: string;
  comments: InstagramArtifactComment[];
};

export function isInstagramPostArtifact(row: WorkspaceArtifact): boolean {
  if (row.kind !== "external_resource") return false;
  const meta = row.metadata ?? {};
  return (
    String(meta.provider ?? "").toLowerCase() === "instagram" &&
    String(meta.resource_type ?? "") === "instagram.post"
  );
}

export async function fetchInstagramArtifactComments(
  token: string,
  organizationId: string,
  workspaceId: number,
  artifactId: string,
): Promise<InstagramArtifactCommentsResponse> {
  const response = await apiFetch(
    `/workspaces/${workspaceId}/artifacts/${artifactId}/instagram/comments/`,
    token,
    organizationId,
  );
  return apiReadJson<InstagramArtifactCommentsResponse>(
    response,
    "Failed to load Instagram comments",
  );
}
