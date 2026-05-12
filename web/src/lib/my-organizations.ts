import type { components } from "@/lib/api/schema";
import { apiFetch, apiReadJson } from "@/lib/api-request";

export type OrganizationResponse = components["schemas"]["OrganizationResponse"];

export async function fetchMyOrganizations(token: string): Promise<OrganizationResponse[]> {
  const response = await apiFetch("/auth/my-organizations", token, null);
  return apiReadJson<OrganizationResponse[]>(response, "Failed to load organizations");
}
