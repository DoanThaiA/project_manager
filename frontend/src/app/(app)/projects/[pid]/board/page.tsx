"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, CornerDownRight, Flag, ListChecks, Plus, Target } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { CompleteSprintModal } from "@/components/project/sprint-modals";
import { LinkedWorkItem } from "@/components/project/linked-work-item";
import { WorkItemModal } from "@/components/project/work-item-modal";
import { MetaBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox, Select } from "@/components/ui/form";
import { Avatar, Card, Empty, ProgressBar, Spinner } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMembers, useProjectId, useProjectPerms, useSprints } from "@/lib/hooks";
import { BOARD_COLUMNS, PRIORITY, WORK_ITEM_STATUS, WORK_ITEM_TYPE } from "@/lib/labels";
import type { Page, WorkItem, WorkItemStatus } from "@/lib/types";
import { cn, daysUntil, fmtDate, fmtHours, num } from "@/lib/utils";

const PRIORITY_BAR: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-orange-500",
  medium: "bg-amber-400",
  low: "bg-sky-400",
  lowest: "bg-slate-300",
};

export default function BoardPage() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const toast = useToast();
  const { me } = useAuth();
  const { can } = useProjectPerms(pid);
  const { byId } = useMembers(pid);
  const sprints = useSprints(pid);
  const [chosen, setChosen] = useState<number | null>(null);
  const [mine, setMine] = useState(false);
  const [openItem, setOpenItem] = useState<WorkItem | null>(null);
  const [creating, setCreating] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [dragOver, setDragOver] = useState<WorkItemStatus | null>(null);

  const selectable = (sprints.data ?? []).filter((s) => s.status !== "cancelled");
  const sprint =
    selectable.find((s) => s.id === chosen) ??
    selectable.find((s) => s.status === "active") ??
    selectable.find((s) => s.status === "planned");

  const itemsKey = ["project", pid, "work-items", { sprint_id: sprint?.id }];
  const items = useQuery({
    queryKey: itemsKey,
    queryFn: async () =>
      (await api.get<Page<WorkItem>>(`/projects/${pid}/work-items`, { params: { sprint_id: sprint!.id, size: 500 } })).data
        .items,
    enabled: !!sprint,
  });

  const move = useMutation({
    mutationFn: ({ id, status }: { id: number; status: WorkItemStatus }) =>
      api.patch(`/projects/${pid}/work-items/${id}`, { status }),
    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: itemsKey });
      const prev = qc.getQueryData<WorkItem[]>(itemsKey);
      qc.setQueryData<WorkItem[]>(itemsKey, (list) => list?.map((w) => (w.id === id ? { ...w, status } : w)));
      return { prev };
    },
    onError: (err, _v, ctx) => {
      qc.setQueryData(itemsKey, ctx?.prev);
      toast.error(err);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["project", pid] }),
  });

  if (sprints.isPending) return <Spinner />;
  if (!sprint)
    return (
      <Empty
        title="Chưa có sprint nào"
        description="Tạo sprint và đưa công việc từ Product Backlog vào để bắt đầu."
        action={
          <Link href={`/projects/${pid}/backlog`}>
            <Button variant="primary">Tới Backlog</Button>
          </Link>
        }
      />
    );

  const all = items.data ?? [];
  const codeById = new Map(all.map((w) => [w.id, w.code]));
  const visible = mine ? all.filter((w) => w.assignee_id === me?.id) : all;
  const planned = all.reduce((s, w) => s + num(w.story_points), 0);
  const done = all.filter((w) => w.status === "done").reduce((s, w) => s + num(w.story_points), 0);
  const unfinished = all.filter((w) => w.status !== "done" && w.status !== "cancelled").length;
  const left = daysUntil(sprint.end_date);
  const canMove = can("work_item.update") && sprint.status !== "completed";

  return (
    <>
      <Card className="mb-4 p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 space-y-1.5">
            <div className="flex items-center gap-2">
              <Select
                aria-label="Chọn sprint"
                className="h-8 w-auto font-semibold"
                value={sprint.id}
                onChange={(e) => setChosen(Number(e.target.value))}
              >
                {selectable.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                    {s.status === "active" ? " (đang chạy)" : s.status === "completed" ? " (đã xong)" : ""}
                  </option>
                ))}
              </Select>
            </div>
            {sprint.goal && (
              <p className="flex items-start gap-1.5 text-sm text-ink-2">
                <Target className="mt-0.5 size-4 shrink-0 text-ink-3" /> {sprint.goal}
              </p>
            )}
            <p className="flex items-center gap-1.5 text-[13px] text-ink-3">
              <CalendarClock className="size-4" />
              {fmtDate(sprint.start_date)} – {fmtDate(sprint.end_date)}
              {sprint.status === "active" && left !== null && (
                <span className={cn(left < 0 && "text-danger")}>
                  · {left >= 0 ? `còn ${left} ngày` : `quá ${-left} ngày`}
                </span>
              )}
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="w-56">
              <div className="mb-1 flex justify-between text-xs text-ink-3">
                <span>Hoàn thành</span>
                <span className="tabular-nums">
                  {done}/{planned} SP
                </span>
              </div>
              <ProgressBar value={planned ? (done / planned) * 100 : 0} />
            </div>
            <div className="flex items-center gap-2">
              <Checkbox label="Chỉ việc của tôi" checked={mine} onChange={(e) => setMine(e.target.checked)} />
              {can("work_item.create") && sprint.status !== "completed" && (
                <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => setCreating(true)}>
                  Thêm việc
                </Button>
              )}
              {sprint.status === "active" && can("sprint.manage") && (
                <Button size="sm" variant="primary" icon={<Flag className="size-3.5" />} onClick={() => setCompleting(true)}>
                  Kết thúc sprint
                </Button>
              )}
            </div>
          </div>
        </div>
        {sprint.status === "planned" && (
          <p className="mt-3 rounded-lg bg-sky-50 px-3 py-2 text-[13px] text-sky-800">
            Sprint chưa bắt đầu. Bắt đầu sprint ở trang Backlog.
          </p>
        )}
      </Card>

      {items.isPending ? (
        <Spinner />
      ) : (
        <div className="grid auto-cols-[minmax(210px,1fr)] grid-flow-col gap-3 overflow-x-auto pb-4">
          {BOARD_COLUMNS.map((col) => {
            const cards = visible
              .filter((w) => (col === "todo" ? w.status === "todo" || w.status === "backlog" : w.status === col))
              .sort((a, b) => PRIORITY[b.priority].rank - PRIORITY[a.priority].rank || a.backlog_rank - b.backlog_rank);
            const colPoints = cards.reduce((s, w) => s + num(w.story_points), 0);
            return (
              <section
                key={col}
                aria-label={WORK_ITEM_STATUS[col].label}
                onDragOver={(e) => {
                  if (!canMove) return;
                  e.preventDefault();
                  setDragOver(col);
                }}
                onDragLeave={() => setDragOver(null)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(null);
                  const id = Number(e.dataTransfer.getData("text/work-item"));
                  const item = all.find((w) => w.id === id);
                  if (item && item.status !== col) move.mutate({ id, status: col });
                }}
                className={cn(
                  "flex min-h-[60vh] flex-col rounded-xl bg-subtle/80 p-2 transition-colors",
                  dragOver === col && "bg-brand-soft ring-2 ring-brand/30",
                )}
              >
                <header className="mb-2 flex items-center justify-between px-1.5 pt-1">
                  <MetaBadge meta={WORK_ITEM_STATUS[col]} />
                  <span className="text-xs text-ink-3 tabular-nums">
                    {cards.length} · {colPoints} SP
                  </span>
                </header>
                <div className="flex flex-1 flex-col gap-2">
                  {cards.map((w) => {
                    const assignee = w.assignee_id ? byId.get(w.assignee_id) : undefined;
                    return (
                      <article
                        key={w.id}
                        draggable={canMove}
                        onDragStart={(e) => {
                          e.dataTransfer.setData("text/work-item", String(w.id));
                          e.dataTransfer.effectAllowed = "move";
                        }}
                        className={cn(
                          "relative overflow-hidden rounded-lg border border-line bg-surface p-3 shadow-card",
                          canMove && "cursor-grab active:cursor-grabbing",
                        )}
                      >
                        <span className={cn("absolute inset-y-0 left-0 w-1", PRIORITY_BAR[w.priority])} aria-hidden />
                        <button type="button" onClick={() => setOpenItem(w)} className="block w-full text-left">
                          {w.parent_id && codeById.has(w.parent_id) && (
                            <p className="mb-0.5 flex items-center gap-1 font-mono text-[11px] text-ink-3">
                              <CornerDownRight className="size-3" /> {codeById.get(w.parent_id)}
                            </p>
                          )}
                          <p className="mb-2 line-clamp-3 text-sm font-medium hover:text-brand">{w.title}</p>
                        </button>
                        <div className="flex items-center gap-1.5">
                          <MetaBadge meta={WORK_ITEM_TYPE[w.type]} dot={false} />
                          <span className="font-mono text-[11px] text-ink-3">{w.code}</span>
                          <span className="ml-auto flex items-center gap-1.5">
                            {w.subtask_count > 0 && (
                              <span
                                className={cn(
                                  "flex items-center gap-0.5 text-[11px] tabular-nums",
                                  w.subtask_done === w.subtask_count ? "text-emerald-600" : "text-ink-3",
                                )}
                                title="Subtask đã xong"
                              >
                                <ListChecks className="size-3.5" />
                                {w.subtask_done}/{w.subtask_count}
                              </span>
                            )}
                            {w.remaining_hours != null && w.status !== "done" && (
                              <span className="text-[11px] text-ink-3 tabular-nums" title="Giờ còn lại">
                                {fmtHours(w.remaining_hours)}
                              </span>
                            )}
                            {w.story_points != null && (
                              <span className="rounded bg-subtle px-1.5 text-[11px] font-semibold tabular-nums">
                                {num(w.story_points)}
                              </span>
                            )}
                            <Avatar size="sm" id={w.assignee_id} name={assignee?.full_name} />
                          </span>
                        </div>
                        {/* Thay thế kéo-thả cho bàn phím / màn hình cảm ứng */}
                        {canMove && (
                          <select
                            aria-label={`Chuyển trạng thái ${w.code}`}
                            value={w.status}
                            onChange={(e) => move.mutate({ id: w.id, status: e.target.value as WorkItemStatus })}
                            className="sr-only focus:not-sr-only focus:mt-2 focus:w-full focus:rounded focus:border focus:border-line focus:text-xs"
                          >
                            {[...BOARD_COLUMNS, "cancelled" as const].map((s) => (
                              <option key={s} value={s}>
                                {WORK_ITEM_STATUS[s].label}
                              </option>
                            ))}
                          </select>
                        )}
                      </article>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {openItem && <WorkItemModal pid={pid} item={openItem} onClose={() => setOpenItem(null)} />}
      <LinkedWorkItem pid={pid} />
      {creating && <WorkItemModal pid={pid} defaults={{ sprint_id: sprint.id }} onClose={() => setCreating(false)} />}
      {completing && (
        <CompleteSprintModal pid={pid} sprint={sprint} unfinished={unfinished} onClose={() => setCompleting(false)} />
      )}
    </>
  );
}
