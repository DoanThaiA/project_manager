"use client";

import { useCallback } from "react";

import type { ActivityResolver } from "@/components/activity-feed";

import { useMembers, useProjectPerms, useRoles, useSprints } from "./hooks";

const USER_FIELDS = new Set([
  "user_id",
  "assignee_id",
  "reporter_id",
  "approved_by",
  "created_by",
  "product_owner_id",
  "scrum_master_id",
]);

/** Đổi id trong nhật ký dự án sang tên: thành viên, sprint, vai trò. */
export function useProjectActivityResolver(pid: number): ActivityResolver {
  const { byId } = useMembers(pid);
  const { can } = useProjectPerms(pid);
  const { data: sprints } = useSprints(pid, can("sprint.view")); // khách hàng không có quyền xem sprint
  const { data: roles } = useRoles();
  return useCallback(
    (field, value) => {
      if (typeof value !== "number") return undefined;
      if (USER_FIELDS.has(field)) return byId.get(value)?.full_name;
      if (field === "sprint_id") return sprints?.find((s) => s.id === value)?.name;
      if (field === "role_id") return roles?.find((r) => r.id === value)?.name;
      return undefined;
    },
    [byId, sprints, roles],
  );
}
