import base64
from typing import Optional
from uuid import UUID

from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction
from django.utils import timezone
from ninja import Router, Schema
from ninja.security import django_auth

from core.models import ApiToken, Organization, OrganizationMember, User
from core.services.auth import ApiKeyAuth, auth_service
from core.services.signup_organization import create_personal_organization_for_signup
from core.utils.schemas import ErrorResponseSchema

router = Router(tags=["Authentication"])


class SignupRequest(Schema):
    email: str
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    organization_id: Optional[UUID] = None


class LoginRequest(Schema):
    email: str
    password: str


class UserResponse(Schema):
    id: int
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    organization: dict
    profile_picture: Optional[str]
    is_active: bool
    is_staff: bool
    onboarding_completed: bool
    created: str


class OrganizationResponse(Schema):
    id: UUID
    name: str
    domain: str
    status: str
    description: str


class UserUpdateRequest(Schema):
    first_name: str
    last_name: str


class OrganizationUpdateRequest(Schema):
    name: Optional[str] = None
    domain: Optional[str] = None


class AuthResponse(Schema):
    api_token: str
    user: UserResponse
    organization: OrganizationResponse


def get_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        organization={
            "id": str(user.organization.id),
            "name": user.organization.name,
            "domain": user.organization.domain,
            "status": user.organization.status,
            "description": user.organization.description,
        },
        profile_picture=user.profile_picture.url if user.profile_picture else None,
        is_active=user.is_active,
        is_staff=user.is_staff,
        onboarding_completed=user.onboarding_completed,
        created=user.created.isoformat(),
    )


def get_organization_response(org: Organization) -> OrganizationResponse:
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        domain=org.domain,
        status=org.status,
        description=org.description,
    )


def get_auth_context(request):
    from core.services.auth import auth_service

    user = auth_service.get_user_from_request(request)
    if user is None:
        return None, None
    return user, user.organization


def ensure_primary_organization_membership(user: User) -> None:
    """IAM row for the user's primary FK organization (required for org-scoped API access)."""
    if not user.organization_id:
        return
    OrganizationMember.objects.get_or_create(
        user=user,
        organization_id=user.organization_id,
        defaults={
            "status": OrganizationMember.Status.ACTIVE,
            "joined_at": timezone.now(),
        },
    )


@router.get("/organizations", response={200: list[OrganizationResponse]})
def list_organizations(request):
    organizations = Organization.objects.filter(status=Organization.Status.ACTIVE)
    return 200, [get_organization_response(org) for org in organizations]


@router.get(
    "/my-organizations",
    response={200: list[OrganizationResponse], 401: ErrorResponseSchema},
    auth=[ApiKeyAuth(), django_auth],
)
def list_my_organizations(request):
    try:
        user, _ = get_auth_context(request)
    except Exception:
        return 401, ErrorResponseSchema(error="Authentication required", error_code="AUTH_REQUIRED")
    if not getattr(user, "is_authenticated", False):
        return 401, ErrorResponseSchema(error="Authentication required", error_code="AUTH_REQUIRED")

    memberships = (
        OrganizationMember.objects.filter(
            user=user,
            status=OrganizationMember.Status.ACTIVE,
            organization__status=Organization.Status.ACTIVE,
        )
        .select_related("organization")
        .order_by("organization__name", "organization_id")
    )
    return 200, [get_organization_response(m.organization) for m in memberships]


@router.post("/signup", response={201: AuthResponse, 400: ErrorResponseSchema})
def signup(request, data: SignupRequest):
    existing_user = User.objects.filter(email=data.email).first()
    if existing_user:
        return 400, ErrorResponseSchema(error="User with this email already exists", error_code="USER_EXISTS")

    with transaction.atomic():
        if data.organization_id:
            organization = Organization.objects.filter(id=data.organization_id).first()
            if not organization:
                return 400, ErrorResponseSchema(
                    error="Invalid organization_id.",
                    error_code="INVALID_ORGANIZATION",
                )
        else:
            organization = create_personal_organization_for_signup(data.email)

        try:
            user = User.objects.create_user(
                email=data.email,
                password=data.password,
                first_name=data.first_name,
                last_name=data.last_name,
                organization=organization,
            )
        except IntegrityError:
            return 400, ErrorResponseSchema(error="User with this email already exists", error_code="USER_EXISTS")

        ensure_primary_organization_membership(user)

        api_token = ApiToken.objects.create(user=user, name="Default Token")
        encoded_token = base64.b64encode(api_token.token.encode()).decode()

    return 201, AuthResponse(
        api_token=encoded_token,
        user=get_user_response(user).dict(),
        organization=get_organization_response(organization).dict(),
    )


@router.post("/login", response={200: AuthResponse, 401: ErrorResponseSchema})
def login(request, data: LoginRequest):
    user = authenticate(email=data.email, password=data.password)
    if not user:
        return 401, ErrorResponseSchema(error="Invalid email or password", error_code="INVALID_CREDENTIALS")
    if not user.is_active:
        return 401, ErrorResponseSchema(error="Account is deactivated", error_code="ACCOUNT_DEACTIVATED")

    ensure_primary_organization_membership(user)

    api_token, _ = ApiToken.objects.get_or_create(user=user, name="Default Token", defaults={"is_active": True})
    encoded_token = base64.b64encode(api_token.token.encode()).decode()
    return 200, AuthResponse(
        api_token=encoded_token,
        user=get_user_response(user).dict(),
        organization=get_organization_response(user.organization).dict(),
    )


@router.get("/me", response={200: UserResponse, 401: ErrorResponseSchema}, auth=[ApiKeyAuth(), django_auth])
def get_current_user(request):
    try:
        user, _organization = get_auth_context(request)
        return 200, get_user_response(user)
    except Exception:
        return 401, ErrorResponseSchema(error="Authentication required", error_code="AUTH_REQUIRED")


@router.patch(
    "/me",
    response={200: UserResponse, 400: ErrorResponseSchema, 401: ErrorResponseSchema},
    auth=[ApiKeyAuth(), django_auth],
)
def patch_current_user(request, data: UserUpdateRequest):
    user = auth_service.get_user_from_request(request)
    if user is None or not getattr(user, "is_authenticated", False):
        return 401, ErrorResponseSchema(error="Authentication required", error_code="AUTH_REQUIRED")

    user.first_name = data.first_name.strip() or None
    user.last_name = data.last_name.strip() or None
    user.save()
    user = User.objects.select_related("organization").get(pk=user.pk)
    return 200, get_user_response(user)


@router.patch(
    "/organization",
    response={
        200: OrganizationResponse,
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def patch_active_organization(request, data: OrganizationUpdateRequest):
    user = auth_service.get_user_from_request(request)
    if user is None or not getattr(user, "is_authenticated", False):
        return 401, ErrorResponseSchema(error="Authentication required", error_code="AUTH_REQUIRED")
    org = auth_service.get_active_organization(request)
    if user.organization_id != org.id:
        return 403, ErrorResponseSchema(
            error="Only users whose primary organization is the active one can edit these settings.",
            error_code="ORG_PRIMARY_REQUIRED",
        )
    if data.name is None and data.domain is None:
        return 400, ErrorResponseSchema(error="No fields to update.", error_code="NO_FIELDS")

    if data.name is not None:
        name = data.name.strip()
        if not name:
            return 400, ErrorResponseSchema(error="Organization name cannot be empty.", error_code="ORG_NAME_INVALID")
        org.name = name[: Organization._meta.get_field("name").max_length]

    if data.domain is not None:
        domain = data.domain.strip()
        if not domain:
            return 400, ErrorResponseSchema(error="Organization domain cannot be empty.", error_code="ORG_DOMAIN_INVALID")
        domain = domain[: Organization._meta.get_field("domain").max_length]
        if Organization.objects.filter(domain=domain).exclude(id=org.id).exists():
            return 400, ErrorResponseSchema(error="That domain is already in use.", error_code="ORG_DOMAIN_TAKEN")
        org.domain = domain

    org.save()
    org.refresh_from_db()
    return 200, get_organization_response(org)


class OnboardingRequest(Schema):
    org_name: str
    org_description: Optional[str] = ""
    workspace_name: str


class OnboardingResponse(Schema):
    user: UserResponse
    organization: OrganizationResponse
    workspace_id: int
    workspace_name: str


@router.post(
    "/onboarding",
    response={200: OnboardingResponse, 400: ErrorResponseSchema, 401: ErrorResponseSchema},
    auth=[ApiKeyAuth(), django_auth],
)
def complete_onboarding(request, data: OnboardingRequest):
    from django.utils import timezone
    from core.models import OrganizationMember, Workspace, WorkspaceMember, Role

    user = auth_service.get_user_from_request(request)
    if user is None or not getattr(user, "is_authenticated", False):
        return 401, ErrorResponseSchema(error="Authentication required", error_code="AUTH_REQUIRED")

    org_name = (data.org_name or "").strip()
    workspace_name = (data.workspace_name or "").strip()
    if not org_name:
        return 400, ErrorResponseSchema(error="Organization name is required.", error_code="ORG_NAME_REQUIRED")
    if not workspace_name:
        return 400, ErrorResponseSchema(error="Workspace name is required.", error_code="WORKSPACE_NAME_REQUIRED")

    with transaction.atomic():
        org = user.organization
        org.name = org_name[:Organization._meta.get_field("name").max_length]
        org.description = (data.org_description or "").strip()
        org.save(update_fields=["name", "description", "modified"])

        role, _ = Role.objects.get_or_create(
            organization=org,
            slug="member",
            defaults={"display_name": "Member", "role_capabilities": []},
        )
        ws = Workspace.objects.create(
            organization=org,
            name=workspace_name[:Workspace._meta.get_field("name").max_length],
        )
        WorkspaceMember.objects.create(
            user=user,
            workspace=ws,
            role=role,
            status=WorkspaceMember.Status.ACTIVE,
            joined_at=timezone.now(),
        )

        from core.services.workspace_starter import bootstrap_workspace
        bootstrap_workspace(workspace=ws, created_by=user)

        user.onboarding_completed = True
        user.save(update_fields=["onboarding_completed"])

    user.refresh_from_db()
    return 200, OnboardingResponse(
        user=get_user_response(user),
        organization=get_organization_response(org),
        workspace_id=ws.id,
        workspace_name=ws.name,
    )


@router.post("/logout", response={200: dict, 401: ErrorResponseSchema}, auth=[ApiKeyAuth(), django_auth])
def logout(request):
    try:
        _user, _organization = get_auth_context(request)
        if hasattr(request, "user") and request.user.is_authenticated:
            from django.contrib.auth import logout as django_logout

            django_logout(request)
        return 200, {"message": "Successfully logged out"}
    except Exception:
        return 401, ErrorResponseSchema(error="Authentication required", error_code="AUTH_REQUIRED")
