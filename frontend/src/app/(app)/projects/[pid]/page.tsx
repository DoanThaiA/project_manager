"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Pencil, Target } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ProjectFormModal } from "@/components/project/project-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, ProgressBar, Spinner, Stat, UserChip } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { useMembers, useProject, useProjectId, useProjectPerms } from "@/lib/hooks";
import { REQUIREMENT_STATUS, WORK_ITEM_STATUS } from "@/lib/labels";
import type { ProjectSummary, RequirementStatus, WorkItemStatus } from "@/lib/types";
import { fmtDate, fmtHours, num } from "@/lib/utils";

function StatusBars<T extends string>({
  counts,
  meta,
}: {
  counts: Record<string, number>;
  meta: Record<T, { label: string }>;
}) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const keys = (Object.keys(meta) as T[]).filter((k) => counts[k]);
  if (!total) return <p className="px-4 py-6 text-sm text-ink-3">Chưa có dữ liệu.</p>;
  return (
    <ul className="space-y-2.5 px-4 py-4">
      {keys.map((k) => (
        <li key={k} className="grid grid-cols-[120px_1fr_32px] items-center gap-3 text-sm">
          <span className="truncate text-ink-2">{meta[k].label}</span>
          <ProgressBar value={(counts[k] / total) * 100} />
          <span className="text-right tabular-nums">{counts[k]}</span>
        </li>
      ))}
    </ul>
  );
}

export default function ProjectOverviewPage() {
  const pid = useProjectId();
  const { data: project } = useProject(pid);
  const { can } = useProjectPerms(pid);
  const { byId } = useMembers(pid);
  const [editing, setEditing] = useState(false);

  const summary = useQuery({
    queryKey: ["project", pid, "summary"],
    queryFn: async () => (await api.get<ProjectSummary>(`/projects/${pid}/reports/summary`)).data,
    enabled: can("report.view"),
  });

  if (!project) return null;
  const s = summary.data;
  const sprint = s?.active_sprint as
    | {
        id: number;
        name: string;
        goal: string | null;
        end_date: string;
        days_left: number;
        planned_points: string;
        completed_points: string;
        remaining_hours: string;
      }
    | null
    | undefined;
  const reqTotal = s ? Object.values(s.requirements_by_status).reduce((a, b) => a + b, 0) : 0;
  const budget = s?.budget_hours != null ? num(s.budget_hours) : null;

  return (
    <div className="space-y-6">
      {s && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Yêu cầu khách hàng" value={reqTotal} sub={`${s.requirements_overdue} quá hạn`} />
          <Stat
            label="Công việc"
            value={Object.values(s.work_items_by_status).reduce((a, b) => a + b, 0)}
            sub={`${s.work_items_by_status.done ?? 0} đã xong`}
          />
          <Stat
            label="Tổng giờ đã log"
            value={fmtHours(s.total_logged_hours)}
            sub={budget ? `/ ${fmtHours(budget)} ngân sách` : undefined}
          />
          <Stat
            label="Sprint hiện tại"
            value={sprint ? sprint.name : "—"}
            sub={sprint ? `Còn ${sprint.days_left} ngày` : "Chưa có sprint chạy"}
          />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader
            title="Thông tin dự án"
            action={
              can("project.update") && (
                <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(true)}>
                  Sửa
                </Button>
              )
            }
          />
          <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-2.5 px-4 py-4 text-sm">
            <dt className="text-ink-3">Product Owner</dt>
            <dd>
              <UserChip id={project.product_owner_id} name={byId.get(project.product_owner_id ?? -1)?.full_name} />
            </dd>
            <dt className="text-ink-3">Scrum Master</dt>
            <dd>
              <UserChip id={project.scrum_master_id} name={byId.get(project.scrum_master_id ?? -1)?.full_name} />
            </dd>
            <dt className="text-ink-3">Thời gian</dt>
            <dd className="tabular-nums">
              {fmtDate(project.start_date)} → {fmtDate(project.end_date)}
            </dd>
            <dt className="text-ink-3">Sprint</dt>
            <dd>{project.sprint_duration_days} ngày</dd>
            {project.description && (
              <>
                <dt className="text-ink-3">Mô tả</dt>
                <dd className="whitespace-pre-line text-ink-2">{project.description}</dd>
              </>
            )}
          </dl>
        </Card>

        {sprint && (
          <Card className="lg:col-span-2">
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  {sprint.name}
                  <Badge tone="green" dot>
                    Đang chạy
                  </Badge>
                </span>
              }
              action={
                <Link href={`/projects/${pid}/board`} className="text-[13px] font-medium text-brand hover:underline">
                  Mở board
                </Link>
              }
            />
            <div className="space-y-4 px-4 py-4">
              {sprint.goal && (
                <p className="flex items-start gap-1.5 text-sm text-ink-2">
                  <Target className="mt-0.5 size-4 shrink-0 text-ink-3" /> {sprint.goal}
                </p>
              )}
              <div>
                <div className="mb-1.5 flex justify-between text-sm">
                  <span className="text-ink-3">Story point hoàn thành</span>
                  <span className="font-medium tabular-nums">
                    {num(sprint.completed_points)} / {num(sprint.planned_points)}
                  </span>
                </div>
                <ProgressBar
                  value={num(sprint.planned_points) ? (num(sprint.completed_points) / num(sprint.planned_points)) * 100 : 0}
                />
              </div>
              <div className="flex flex-wrap gap-6 text-sm">
                <span className="flex items-center gap-1.5 text-ink-2">
                  <CalendarClock className="size-4 text-ink-3" /> Kết thúc {fmtDate(sprint.end_date)} · còn{" "}
                  {sprint.days_left} ngày
                </span>
                <span className="text-ink-2">Giờ còn lại: {fmtHours(sprint.remaining_hours)}</span>
              </div>
            </div>
          </Card>
        )}

        {summary.isPending && can("report.view") && <Spinner />}
      </div>

      {s && (
        <div className="grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader title="Yêu cầu theo trạng thái" />
            <StatusBars<RequirementStatus> counts={s.requirements_by_status} meta={REQUIREMENT_STATUS} />
          </Card>
          <Card>
            <CardHeader title="Công việc theo trạng thái" />
            <StatusBars<WorkItemStatus> counts={s.work_items_by_status} meta={WORK_ITEM_STATUS} />
          </Card>
        </div>
      )}

      {editing && <ProjectFormModal project={project} onClose={() => setEditing(false)} />}
    </div>
  );
}
