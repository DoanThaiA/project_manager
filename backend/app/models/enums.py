"""Khớp 1-1 với các ENUM trong migrations/sql/0001_init_schema.sql."""

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


class CrmContactStatus(StrEnum):
    """Trạng thái theo dõi khách liên hệ CRM (cột crm_contacts.status, CHECK constraint)."""

    new = "new"
    contacted = "contacted"  # đã liên hệ lại
    quoted = "quoted"  # đã gửi báo giá
    negotiating = "negotiating"  # đang thương lượng
    won = "won"  # chốt đơn
    lost = "lost"  # không thành
    spam = "spam"


class CrmInquiryType(StrEnum):
    """Loại nhu cầu trong email (cột crm_email_leads.inquiry_type, CHECK constraint) - giá trị n8n gửi sang."""

    dat_hang = "dat_hang"  # đặt hàng
    bao_gia = "bao_gia"  # xin báo giá
    hoi_thong_tin = "hoi_thong_tin"  # hỏi thông tin
    khac = "khac"


class TextFileFolder(StrEnum):
    """Nhóm (folder trên R2) của file gắn trong ô văn bản: projects/<id>/text/<nhóm>/..."""

    work_items = "work-items"  # mô tả / tiêu chí hoàn thành công việc
    requirements = "requirements"  # mô tả / tiêu chí nghiệm thu yêu cầu
    requirement_comments = "requirement-comments"  # bình luận yêu cầu
    requirement_status = "requirement-status"  # ghi chú khi chuyển trạng thái yêu cầu
    work_logs = "work-logs"  # log công việc
    sprints = "sprints"  # sprint review / retrospective
    other = "other"


class NotificationEvent(StrEnum):
    """Loại sự kiện gửi thông báo Telegram."""

    work_item_status_changed = "work_item.status_changed"
    work_item_created = "work_item.created"
    work_item_assigned = "work_item.assigned"
    work_log_created = "work_log.created"
    requirement_created = "requirement.created"
    requirement_status_changed = "requirement.status_changed"
    requirement_commented = "requirement.commented"
    sprint_status_changed = "sprint.status_changed"


class NotificationScope(StrEnum):
    all = "all"  # group: mọi thay đổi của dự án; cá nhân: mọi thay đổi trong các dự án mình tham gia
    mine = "mine"  # cá nhân: chỉ việc / yêu cầu giao cho mình, mình tạo (hoặc mình đã bình luận)
