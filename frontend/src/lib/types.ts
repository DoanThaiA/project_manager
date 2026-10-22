// Kiểu dữ liệu lấy từ OpenAPI của backend — sinh lại bằng `npm run gen:api`
import type { components } from "./api-schema";

type S = components["schemas"];

export type Page<T> = { items: T[]; total: number; page: number; size: number };

export type Me = S["MeOut"];
export type User = S["UserOut"];
export type UserDetail = S["UserDetail"];
export type UserBrief = S["UserBrief"];
export type Role = S["RoleOut"];
export type RoleDetail = S["RoleDetail"];
export type Permission = S["PermissionOut"];

export type Customer = S["CustomerOut"];
export type CustomerOcr = S["CustomerOcrOut"];
export type Contact = S["ContactOut"];
export type ContactOcr = S["ContactOcrOut"];

export type Project = S["ProjectOut"];
export type ProjectCreate = S["ProjectCreate"];
export type ProjectSummary = S["ProjectSummary"];
export type Member = S["MemberOut"];
export type Sprint = S["SprintOut"];
export type SprintProgress = S["SprintProgress"];

export type Requirement = S["RequirementOut"];
export type RequirementDetail = S["RequirementDetail"];
export type RequirementCreate = S["RequirementCreate"];
export type StatusHistory = S["StatusHistoryOut"];
export type Comment = S["CommentOut"];

export type WorkItem = S["WorkItemOut"];
export type WorkItemCreate = S["WorkItemCreate"];
export type WorkLog = S["WorkLogOut"];
export type Attachment = S["AttachmentOut"];
export type AttachmentCategory = NonNullable<Attachment["category"]>;
export type WorkLogSummaryRow = S["WorkLogSummaryRow"];
export type ActivityLog = S["ActivityLogOut"];

export type RequirementStatus = Requirement["status"];
export type RequirementType = Requirement["type"];
export type RequirementSource = Requirement["source"];
export type Priority = Requirement["priority"];
export type WorkItemStatus = WorkItem["status"];
export type WorkItemType = WorkItem["type"];
export type ActivityType = WorkLog["activity_type"];
export type SprintStatus = Sprint["status"];
export type ProjectStatus = Project["status"];
