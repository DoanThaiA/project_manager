"""Khớp 1-1 với các ENUM trong db/migrations/V1__init_schema.sql."""

from enum import StrEnum


class UserStatus(StrEnum):
    active = "active"
    inactive = "inactive"
    locked = "locked"


class RoleScope(StrEnum):
    system = "system"
    project = "project"


class CustomerStatus(StrEnum):
    active = "active"
    inactive = "inactive"


class ProjectStatus(StrEnum):
    planning = "planning"
    active = "active"
    on_hold = "on_hold"
    completed = "completed"
    cancelled = "cancelled"


class SprintStatus(StrEnum):
    planned = "planned"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class PriorityLevel(StrEnum):
    lowest = "lowest"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class RequirementType(StrEnum):
    feature = "feature"
    change_request = "change_request"
    bug = "bug"
    improvement = "improvement"
    support = "support"
    other = "other"


class RequirementSource(StrEnum):
    email = "email"
    meeting = "meeting"
    phone = "phone"
    chat = "chat"
    ticket = "ticket"
    document = "document"
    other = "other"


class RequirementStatus(StrEnum):
    new = "new"
    analyzing = "analyzing"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    in_progress = "in_progress"
    done = "done"
    closed = "closed"
    cancelled = "cancelled"


class WorkItemType(StrEnum):
    epic = "epic"
    story = "story"
    task = "task"
    bug = "bug"
    subtask = "subtask"


class WorkItemStatus(StrEnum):
    backlog = "backlog"
    todo = "todo"
    in_progress = "in_progress"
    in_review = "in_review"
    testing = "testing"
    done = "done"
    cancelled = "cancelled"


class WorkActivityType(StrEnum):
    analysis = "analysis"
    design = "design"
    development = "development"
    testing = "testing"
    review = "review"
    meeting = "meeting"
    deployment = "deployment"
    support = "support"
    documentation = "documentation"
    other = "other"


class AttachmentCategory(StrEnum):
    """Phân loại ảnh đính kèm công việc (cột attachments.category, CHECK constraint, không phải ENUM)."""

    bug = "bug"  # ảnh chụp lỗi
    result = "result"  # ảnh kết quả sau khi sửa
