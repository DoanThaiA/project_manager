import type {
  ActivityType,
  Priority,
  ProjectStatus,
  RequirementSource,
  RequirementStatus,
  RequirementType,
  SprintStatus,
  WorkItemStatus,
  WorkItemType,
} from "./types";

export type Tone = "gray" | "blue" | "indigo" | "violet" | "amber" | "green" | "red" | "teal" | "orange";

type Meta = { label: string; tone: Tone };

export const REQUIREMENT_STATUS: Record<RequirementStatus, Meta> = {
  new: { label: "Mới", tone: "blue" },
  analyzing: { label: "Đang phân tích", tone: "violet" },
  pending_approval: { label: "Chờ duyệt", tone: "amber" },
  approved: { label: "Đã duyệt", tone: "teal" },
  rejected: { label: "Từ chối", tone: "red" },
  in_progress: { label: "Đang thực hiện", tone: "indigo" },
  done: { label: "Hoàn thành", tone: "green" },
  closed: { label: "Đã đóng", tone: "gray" },
  cancelled: { label: "Huỷ", tone: "gray" },
};

// Khớp TRANSITIONS trong backend/app/api/v1/endpoints/requirements.py
export const REQUIREMENT_TRANSITIONS: Record<RequirementStatus, RequirementStatus[]> = {
  new: ["analyzing", "pending_approval", "approved", "rejected", "cancelled"],
  analyzing: ["new", "pending_approval", "approved", "rejected", "cancelled"],
  pending_approval: ["analyzing", "approved", "rejected", "cancelled"],
  approved: ["analyzing", "in_progress", "cancelled"],
  rejected: ["new"],
  in_progress: ["approved", "done", "cancelled"],
  done: ["in_progress", "closed"],
  closed: ["in_progress"],
  cancelled: ["new"],
};
export const APPROVAL_STATUSES: RequirementStatus[] = ["approved", "rejected"];

export const REQUIREMENT_TYPE: Record<RequirementType, string> = {
  feature: "Tính năng",
  change_request: "Thay đổi",
  bug: "Lỗi",
  improvement: "Cải tiến",
  support: "Hỗ trợ",
  other: "Khác",
};

export const REQUIREMENT_SOURCE: Record<RequirementSource, string> = {
  email: "Email",
  meeting: "Cuộc họp",
  phone: "Điện thoại",
  chat: "Chat",
  ticket: "Ticket",
  document: "Tài liệu",
  other: "Khác",
};

export const PRIORITY: Record<Priority, Meta & { rank: number }> = {
  critical: { label: "Khẩn cấp", tone: "red", rank: 5 },
  high: { label: "Cao", tone: "orange", rank: 4 },
  medium: { label: "Trung bình", tone: "amber", rank: 3 },
  low: { label: "Thấp", tone: "blue", rank: 2 },
  lowest: { label: "Rất thấp", tone: "gray", rank: 1 },
};

export const WORK_ITEM_STATUS: Record<WorkItemStatus, Meta> = {
  backlog: { label: "Backlog", tone: "gray" },
  todo: { label: "Cần làm", tone: "blue" },
  in_progress: { label: "Đang làm", tone: "indigo" },
  in_review: { label: "Review", tone: "violet" },
  testing: { label: "Kiểm thử", tone: "amber" },
  done: { label: "Xong", tone: "green" },
  cancelled: { label: "Huỷ", tone: "gray" },
};
export const BOARD_COLUMNS: WorkItemStatus[] = ["todo", "in_progress", "in_review", "testing", "done"];

export const WORK_ITEM_TYPE: Record<WorkItemType, Meta> = {
  epic: { label: "Epic", tone: "violet" },
  story: { label: "Story", tone: "green" },
  task: { label: "Task", tone: "blue" },
  bug: { label: "Bug", tone: "red" },
  subtask: { label: "Subtask", tone: "gray" },
};

export const ACTIVITY_TYPE: Record<ActivityType, string> = {
  analysis: "Phân tích",
  design: "Thiết kế",
  development: "Lập trình",
  testing: "Kiểm thử",
  review: "Review",
  meeting: "Họp",
  deployment: "Triển khai",
  support: "Hỗ trợ",
  documentation: "Tài liệu",
  other: "Khác",
};

export const SPRINT_STATUS: Record<SprintStatus, Meta> = {
  planned: { label: "Kế hoạch", tone: "blue" },
  active: { label: "Đang chạy", tone: "green" },
  completed: { label: "Đã xong", tone: "gray" },
  cancelled: { label: "Huỷ", tone: "gray" },
};

export const PROJECT_STATUS: Record<ProjectStatus, Meta> = {
  planning: { label: "Lên kế hoạch", tone: "blue" },
  active: { label: "Đang chạy", tone: "green" },
  on_hold: { label: "Tạm dừng", tone: "amber" },
  completed: { label: "Hoàn thành", tone: "gray" },
  cancelled: { label: "Huỷ", tone: "gray" },
};

export const ACTION_LABEL: Record<string, string> = {
  create: "Tạo mới",
  update: "Cập nhật",
  delete: "Xoá",
  soft_delete: "Xoá",
  restore: "Khôi phục",
  status_change: "Đổi trạng thái",
  member_add: "Thêm thành viên",
  member_remove: "Bỏ thành viên",
  login: "Đăng nhập",
  login_failed: "Đăng nhập thất bại",
};

export const ENTITY_LABEL: Record<string, string> = {
  users: "Người dùng",
  customers: "Khách hàng",
  projects: "Dự án",
  project_members: "Thành viên",
  sprints: "Sprint",
  requirements: "Yêu cầu",
  requirement_comments: "Bình luận",
  work_items: "Công việc",
  work_logs: "Log công việc",
  attachments: "File đính kèm",
};

export const FIELD_LABEL: Record<string, string> = {
  status: "Trạng thái",
  title: "Tiêu đề",
  description: "Mô tả",
  priority: "Ưu tiên",
  assignee_id: "Người phụ trách",
  due_date: "Hạn",
  sprint_id: "Sprint",
  story_points: "Story point",
  remaining_hours: "Giờ còn lại",
  hours: "Số giờ",
  approved_at: "Thời điểm duyệt",
  approved_by: "Người duyệt",
  completed_at: "Hoàn thành lúc",
  rejected_reason: "Lý do từ chối",
  last_login_at: "Đăng nhập lần cuối",
  deleted_at: "Xoá lúc",
  name: "Tên",
  goal: "Mục tiêu",
  backlog_rank: "Thứ tự backlog",
  retrospective_note: "Retrospective",
  review_note: "Sprint review",
  role_id: "Vai trò",
  requirement_id: "Yêu cầu",
  reporter_id: "Người tạo",
  product_owner_id: "Product Owner",
  scrum_master_id: "Scrum Master",
  is_primary: "Đầu mối chính",
  is_internal: "Nội bộ",
  content: "Nội dung",
  type: "Loại",
  start_date: "Ngày bắt đầu",
  end_date: "Ngày kết thúc",
  original_estimate_hours: "Ước lượng (h)",
  estimated_hours: "Ước lượng (h)",
  is_billable: "Tính phí",
  log_date: "Ngày log",
  activity_type: "Loại việc",
  acceptance_criteria: "Tiêu chí nghiệm thu",
  expected_date: "Ngày KH mong muốn",
  business_value: "Giá trị KD",
  resolved_at: "Hoàn thành lúc",
  closed_at: "Đóng lúc",
};

export function labelOf(map: Record<string, string>, key: string) {
  return map[key] ?? key;
}
