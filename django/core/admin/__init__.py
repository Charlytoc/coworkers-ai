from django.contrib import admin

from core.admin.agent_session_log import AgentSessionLogAdmin
from core.admin.api_token import ApiTokenAdmin
from core.admin.artifact import ArtifactAdmin
from core.admin.conversation import ConversationAdmin
from core.admin.cyber_identity import CyberIdentityAdmin
from core.admin.message import MessageAdmin
from core.admin.identity_asset import IdentityAssetAdmin
from core.admin.integration_account import IntegrationAccountAdmin
from core.admin.integration_event import IntegrationEventAdmin
from core.admin.job_assignment import JobAssignmentAdmin
from core.admin.media_object import MediaObjectAdmin
from core.admin.memory import MemoryAdmin
from core.admin.organization import OrganizationAdmin
from core.admin.organization_member import OrganizationMemberAdmin
from core.admin.role import RoleAdmin
from core.admin.task_execution import TaskExecutionAdmin
from core.admin.user import UserAdmin
from core.admin.workspace import WorkspaceAdmin
from core.admin.workspace_member import WorkspaceMemberAdmin
from core.models import (
    AgentSessionLog,
    ApiToken,
    Artifact,
    Conversation,
    CyberIdentity,
    IdentityAsset,
    IntegrationAccount,
    IntegrationEvent,
    JobAssignment,
    MediaObject,
    Memory,
    Message,
    Organization,
    OrganizationMember,
    Role,
    TaskExecution,
    User,
    Workspace,
    WorkspaceMember,
)

admin.site.register(User, UserAdmin)
admin.site.register(Organization, OrganizationAdmin)
admin.site.register(OrganizationMember, OrganizationMemberAdmin)
admin.site.register(Role, RoleAdmin)
admin.site.register(Workspace, WorkspaceAdmin)
admin.site.register(WorkspaceMember, WorkspaceMemberAdmin)
admin.site.register(MediaObject, MediaObjectAdmin)
admin.site.register(CyberIdentity, CyberIdentityAdmin)
admin.site.register(Memory, MemoryAdmin)
admin.site.register(IdentityAsset, IdentityAssetAdmin)
admin.site.register(IntegrationAccount, IntegrationAccountAdmin)
admin.site.register(IntegrationEvent, IntegrationEventAdmin)
admin.site.register(JobAssignment, JobAssignmentAdmin)
admin.site.register(TaskExecution, TaskExecutionAdmin)
admin.site.register(Artifact, ArtifactAdmin)
admin.site.register(ApiToken, ApiTokenAdmin)
admin.site.register(AgentSessionLog, AgentSessionLogAdmin)
admin.site.register(Conversation, ConversationAdmin)
admin.site.register(Message, MessageAdmin)
