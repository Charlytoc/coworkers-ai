import type { components } from "@/lib/api/schema";
import { apiFetch, apiReadJson } from "@/lib/api-request";

export type UserResponse = components["schemas"]["UserResponse"];
export type OrganizationResponse = components["schemas"]["OrganizationResponse"];

export async function fetchCurrentUser(token: string): Promise<UserResponse> {
  const response = await apiFetch("/auth/me", token, null);
  return apiReadJson<UserResponse>(response, "Failed to load profile");
}

export async function patchCurrentUser(
  token: string,
  body: components["schemas"]["UserUpdateRequest"],
): Promise<UserResponse> {
  const response = await apiFetch("/auth/me", token, null, {
    method: "PATCH",
    jsonBody: body,
  });
  return apiReadJson<UserResponse>(response, "Failed to update profile");
}

export async function patchActiveOrganization(
  token: string,
  organizationId: string,
  body: components["schemas"]["OrganizationUpdateRequest"],
): Promise<OrganizationResponse> {
  const response = await apiFetch("/auth/organization", token, organizationId, {
    method: "PATCH",
    jsonBody: body,
  });
  return apiReadJson<OrganizationResponse>(response, "Failed to update organization");
}
