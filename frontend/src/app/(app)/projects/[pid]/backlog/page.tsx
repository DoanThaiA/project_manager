"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ChevronDown, GripVertical, Play, Plus } from "lucide-react";
import { useState } from "react";

import { SprintSelect } from "@/components/project/selects";
import { CreateSprintModal } from "@/components/project/sprint-modals";
import { WorkItemModal } from "@/components/project/work-item-modal";
import { Badge, MetaBadge } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { Avatar, Card, Spinner } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useMembers, useProjectId, useProjectPerms, useSprints } from "@/lib/hooks";
import { PRIORITY, SPRINT_STATUS, WORK_ITEM_STATUS, WORK_ITEM_TYPE } from "@/lib/labels";
import type { Page, Sprint, WorkItem } from "@/lib/types";
import { cn, fmtDate, num } from "@/lib/utils";

type Section = { key: string; sprint: Sprint | null; items: WorkItem[] };

export default function BacklogPage() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useProjectPerms(pid);
  const { byId } = useMembers(pid);
  const sprints = useSprints(pid);
  const [creating, setCreating] = useState<{ sprint_id: number | null } | null>(null);
  const [sprintModal, setSprintModal] = useState(false);
  const [openItem, setOpenItem] = useState<WorkItem | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [dragOver, setDragOver] = useState<string | null>(null);
  const canEdit = can("work_item.update");

  const itemsKey = ["project", pid, "work-items", "backlog-view"];
  const items = useQuery({
    queryKey: itemsKey,
    queryFn: async () =>
      (
        await api.get<Page<WorkItem>>(`/projects/${pid}/work-items`, {
          params: { status: ["backlog", "todo", "in_progress", "in_review", "testing", "done"], size: 500 },
        })
      ).data.items,
  });

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<WorkItem> }) =>
      api.patch(`/projects/${pid}/work-items/${id}`, body),
    onMutate: async ({ id, body }) => {
      await qc.cancelQueries({ queryKey: itemsKey });
      const prev = qc.getQueryData<WorkItem[]>(itemsKey);
      qc.setQueryData<WorkItem[]>(itemsKey, (list) => list?.map((w) => (w.id === id ? { ...w, ...body } : w)));
      return { prev };
    },
    onError: (err, _v, ctx) => {
      qc.setQueryData(itemsKey, ctx?.prev);
      toast.error(err);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["project", pid] }),
  });

  const startSprint = useMutation({
    mutationFn: (sid: number) => api.post(`/projects/${pid}/sprints/${sid}/start`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", pid] });
      toast.success("Sprint đã bắt đầu");
    },
    onError: toast.error,
  });

  if (items.isPending || sprints.isPending) return <Spinner />;

  const all = items.data ?? [];
  const openSprints = (sprints.data ?? [])
    .filter((s) => s.status === "active" || s.status === "planned")
    .sort((a, b) => a.sprint_no - b.sprint_no);
  const hasActive = openSprints.some((s) => s.status === "active");
  const sections: Section[] = [
    ...openSprints.map((s) => ({ key: `s${s.id}`, sprint: s, items: all.filter((w) => w.sprint_id === s.id) })),
    {
      key: "backlog",
      sprint: null,
      items: all.filter((w) => w.sprint_id === null && w.status !== "done"),
    },
  ];

  /** Đổi chỗ với hàng kế bên trong backlog bằng cách đặt rank vào giữa. */
  function move(list: WorkItem[], index: number, dir: -1 | 1) {
    const target = index + dir;
    if (target < 0 || target >= list.length) return;
    const neighbor = list[target + dir];
    const pivot = list[target].backlog_rank;
    const rank = neighbor ? (pivot + neighbor.backlog_rank) / 2 : pivot + dir;
    patch.mutate({ id: list[index].id, body: { backlog_rank: rank } });
  }

  function onDrop(section: Section, e: React.DragEvent) {
    e.preventDefault();
    setDragOver(null);
    const id = Number(e.dataTransfer.getData("text/work-item"));
    const item = all.find((w) => w.id === id);
    const sprintId = section.sprint?.id ?? null;
    if (item && item.sprint_id !== sprintId) {
      patch.mutate({
        id,
        body: {
          sprint_id: sprintId,
          ...(sprintId === null ? { status: "backlog" } : item.status === "backlog" ? { status: "todo" } : {}),
        },
      });
    }
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-ink-3">
          Kéo thả công việc giữa Product Backlog và các sprint để lập kế hoạch.
        </p>
        <div className="flex gap-2">
          {can("sprint.manage") && (
            <Button icon={<Plus className="size-4" />} onClick={() => setSprintModal(true)}>
              Sprint mới
            </Button>
          )}
          {can("work_item.create") && (
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating({ sprint_id: null })}>
              Công việc mới
            </Button>
          )}
        </div>
      </div>

      <div className="space-y-4">
        {sections.map((section) => {
          const sorted = [...section.items].sort((a, b) => a.backlog_rank - b.backlog_rank || a.id - b.id);
          const points = sorted.reduce((s, w) => s + num(w.story_points), 0);
          const isCollapsed = collapsed[section.key];
          const s = section.sprint;
          return (
            <Card
              key={section.key}
              className={cn("transition-shadow", dragOver === section.key && "ring-2 ring-brand/40")}
            >
              <div
                onDragOver={(e) => {
                  if (!canEdit) return;
                  e.preventDefault();
                  setDragOver(section.key);
                }}
                onDragLeave={() => setDragOver(null)}
                onDrop={(e) => onDrop(section, e)}
              >
                <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
                  <button
                    type="button"
                    aria-expanded={!isCollapsed}
                    onClick={() => setCollapsed((c) => ({ ...c, [section.key]: !c[section.key] }))}
                    className="flex items-center gap-2 text-sm font-semibold"
                  >
                    <ChevronDown className={cn("size-4 text-ink-3 transition-transform", isCollapsed && "-rotate-90")} />
                    {s ? s.name : "Product Backlog"}
                  </button>
                  {s && <MetaBadge meta={SPRINT_STATUS[s.status]} />}
                  {s && (
                    <span className="text-xs text-ink-3 tabular-nums">
                      {fmtDate(s.start_date)} – {fmtDate(s.end_date)}
                    </span>
                  )}
                  <span className="text-xs text-ink-3">
                    · {sorted.length} việc · {points} SP
                  </span>
                  <div className="ml-auto flex gap-2">
                    {s?.status === "planned" && can("sprint.manage") && (
                      <Button
                        size="sm"
                        icon={<Play className="size-3.5" />}
                        disabled={hasActive}
                        title={hasActive ? "Đang có sprint chạy" : undefined}
                        loading={startSprint.isPending && startSprint.variables === s.id}
                        onClick={() => startSprint.mutate(s.id)}
                      >
                        Bắt đầu sprint
                      </Button>
                    )}
                    {can("work_item.create") && (
                      <IconButton label="Thêm công việc" onClick={() => setCreating({ sprint_id: s?.id ?? null })}>
                        <Plus className="size-4" />
                      </IconButton>
                    )}
                  </div>
                </div>
                {s?.goal && !isCollapsed && <p className="border-b border-line px-4 py-2 text-[13px] text-ink-2">{s.goal}</p>}

                {!isCollapsed &&
                  (sorted.length === 0 ? (
                    <p className="px-4 py-6 text-center text-sm text-ink-3">
                      {s ? "Kéo công việc từ backlog vào đây" : "Backlog trống"}
                    </p>
                  ) : (
                    <ul className="divide-y divide-line">
                      {sorted.map((w, i) => (
                        <li
                          key={w.id}
                          draggable={canEdit}
                          onDragStart={(e) => {
                            e.dataTransfer.setData("text/work-item", String(w.id));
                            e.dataTransfer.effectAllowed = "move";
                          }}
                          className="group flex items-center gap-2 px-2 py-1.5 text-sm hover:bg-subtle/60"
                        >
                          {canEdit && <GripVertical className="size-4 shrink-0 cursor-grab text-ink-3/50" aria-hidden />}
                          <MetaBadge meta={WORK_ITEM_TYPE[w.type]} dot={false} />
                          <button
                            type="button"
                            onClick={() => setOpenItem(w)}
                            className="flex min-w-0 flex-1 items-center gap-2 text-left"
                          >
                            <span className="shrink-0 font-mono text-xs text-ink-3">{w.code}</span>
                            <span
                              className={cn("truncate hover:text-brand", w.status === "done" && "text-ink-3 line-through")}
                            >
                              {w.title}
                            </span>
                          </button>
                          <span className="hidden sm:inline-flex">
                            <MetaBadge meta={PRIORITY[w.priority]} dot={false} />
                          </span>
                          {s && <MetaBadge meta={WORK_ITEM_STATUS[w.status]} />}
                          <Badge className="w-12 justify-center tabular-nums">{w.story_points != null ? num(w.story_points) : "–"}</Badge>
                          <Avatar
                            size="sm"
                            id={w.assignee_id}
                            name={w.assignee_id ? byId.get(w.assignee_id)?.full_name : null}
                          />
                          {canEdit && (
                            <>
                              <SprintSelect
                                aria-label={`Chuyển ${w.code} sang sprint`}
                                className="hidden h-7 w-48 text-xs md:block"
                                pid={pid}
                                value={w.sprint_id}
                                onChange={(v) =>
                                  patch.mutate({
                                    id: w.id,
                                    body: { sprint_id: v, ...(v === null ? { status: "backlog" } : {}) },
                                  })
                                }
                              />
                              {!s && (
                                <span className="flex opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                                  <IconButton label="Lên" className="size-7" disabled={i === 0} onClick={() => move(sorted, i, -1)}>
                                    <ArrowUp className="size-3.5" />
                                  </IconButton>
                                  <IconButton
                                    label="Xuống"
                                    className="size-7"
                                    disabled={i === sorted.length - 1}
                                    onClick={() => move(sorted, i, 1)}
                                  >
                                    <ArrowDown className="size-3.5" />
                                  </IconButton>
                                </span>
                              )}
                            </>
                          )}
                        </li>
                      ))}
                    </ul>
                  ))}
              </div>
            </Card>
          );
        })}
      </div>

      {creating && <WorkItemModal pid={pid} defaults={creating} onClose={() => setCreating(null)} />}
      {openItem && <WorkItemModal pid={pid} item={openItem} onClose={() => setOpenItem(null)} />}
      {sprintModal && <CreateSprintModal pid={pid} onClose={() => setSprintModal(false)} />}
    </>
  );
}
