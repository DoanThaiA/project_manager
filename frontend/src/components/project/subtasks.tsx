"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { MemberSelect } from "@/components/project/selects";
import { MetaBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { Avatar, ProgressBar } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMembers, useProjectPerms } from "@/lib/hooks";
import { WORK_ITEM_STATUS } from "@/lib/labels";
import type { Page, WorkItem, WorkItemStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Danh sách subtask của một công việc: tick để đánh dấu xong, thêm nhanh bằng tiêu đề.
 * Backend tự chuyển công việc cha: có subtask bắt đầu -> Đang làm, mọi subtask xong -> Xong.
 */
export function Subtasks({
  pid,
  parent,
  canEdit,
  onOpen,
}: {
  pid: number;
  parent: WorkItem;
  canEdit: boolean;
  onOpen: (item: WorkItem) => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const { me } = useAuth();
  const { can } = useProjectPerms(pid);
  const { byId } = useMembers(pid);
  const [title, setTitle] = useState("");
  const [assignee, setAssignee] = useState<number | null>(null);
  const queryKey = ["project", pid, "work-items", { parent_id: parent.id }];

  const subtasks = useQuery({
    queryKey,
    queryFn: async () =>
      (await api.get<Page<WorkItem>>(`/projects/${pid}/work-items`, { params: { parent_id: parent.id, size: 200 } })).data
        .items,
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["project", pid] });

  const add = useMutation({
    mutationFn: () =>
      api.post<WorkItem>(`/projects/${pid}/work-items`, {
        title: title.trim(),
        parent_id: parent.id,
        priority: parent.priority,
        assignee_id: assignee,
      }),
    onSuccess: () => {
      setTitle("");
      return refresh();
    },
    onError: toast.error,
  });

  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: number; status: WorkItemStatus }) =>
      api.patch(`/projects/${pid}/work-items/${id}`, { status }),
    onSettled: refresh,
    onError: toast.error,
  });

  const list = subtasks.data ?? [];
  const counted = list.filter((s) => s.status !== "cancelled");
  const done = counted.filter((s) => s.status === "done").length;
  const reopenStatus = (s: WorkItem): WorkItemStatus => (s.sprint_id ? "todo" : "backlog");

  return (
    <div>
      {list.length > 0 && (
        <div className="mb-2 flex items-center gap-3">
          <ProgressBar value={counted.length ? (done / counted.length) * 100 : 0} className="flex-1" />
          <span className="text-xs text-ink-3 tabular-nums">
            {done}/{counted.length} xong
          </span>
        </div>
      )}

      {subtasks.isPending ? (
        <p className="py-2 text-sm text-ink-3">Đang tải…</p>
      ) : list.length === 0 ? (
        <p className="py-1 text-sm text-ink-3">
          Chưa có subtask.{canEdit && " Chia nhỏ công việc — khi mọi subtask xong, công việc này tự chuyển sang Xong."}
        </p>
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {list.map((s) => {
            const finished = s.status === "done" || s.status === "cancelled";
            return (
              <li key={s.id} className="flex items-center gap-2.5 px-3 py-2 text-sm">
                <input
                  type="checkbox"
                  aria-label={`Đánh dấu ${s.code} ${s.status === "done" ? "chưa xong" : "xong"}`}
                  className="size-4 shrink-0 rounded border-line-strong accent-brand"
                  checked={s.status === "done"}
                  disabled={!canEdit || s.status === "cancelled" || setStatus.isPending}
                  onChange={(e) => setStatus.mutate({ id: s.id, status: e.target.checked ? "done" : reopenStatus(s) })}
                />
                <button
                  type="button"
                  onClick={() => onOpen(s)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                >
                  <span className="shrink-0 font-mono text-xs text-ink-3">{s.code}</span>
                  <span className={cn("truncate hover:text-brand", finished && "text-ink-3 line-through")}>
                    {s.title}
                  </span>
                </button>
                <MetaBadge meta={WORK_ITEM_STATUS[s.status]} />
                <Avatar size="sm" id={s.assignee_id} name={s.assignee_id ? byId.get(s.assignee_id)?.full_name : null} />
              </li>
            );
          })}
        </ul>
      )}

      {canEdit && can("work_item.create") && (
        <form
          className="mt-2 flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim()) add.mutate();
          }}
        >
          <Input
            aria-label="Tiêu đề subtask"
            placeholder="Thêm subtask… (Enter để thêm)"
            className="min-w-48 flex-1"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <MemberSelect
            aria-label="Người thực hiện subtask"
            className="w-44"
            pid={pid}
            value={assignee}
            onChange={setAssignee}
            disabled={!can("work_item.assign") && assignee !== me?.id && assignee !== null}
          />
          <Button
            type="submit"
            size="sm"
            className="h-9"
            icon={<Plus className="size-3.5" />}
            loading={add.isPending}
            disabled={!title.trim()}
          >
            Thêm
          </Button>
        </form>
      )}
    </div>
  );
}
