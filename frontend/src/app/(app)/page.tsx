"use client";

import { useQuery } from "@tanstack/react-query";
import { startOfWeek, format } from "date-fns";
import { ArrowRight, Clock, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { WorkLogModal } from "@/components/project/work-log-form";
import { MetaBadge } from "@/components/ui/badge";
import { TextImagesButton, withoutImages } from "@/components/text-images";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Empty, PageHeader, Spinner, Stat } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useProjects } from "@/lib/hooks";
import { ACTIVITY_TYPE, PROJECT_STATUS } from "@/lib/labels";
import type { Page, WorkLog } from "@/lib/types";
import { fmtDate, fmtHours, num } from "@/lib/utils";

export default function DashboardPage() {
  const { me } = useAuth();
  const projects = useProjects();
  const [logOpen, setLogOpen] = useState(false);
  const weekStart = format(startOfWeek(new Date(), { weekStartsOn: 1 }), "yyyy-MM-dd");

  const weekLogs = useQuery({
    queryKey: ["me", "work-logs", { from: weekStart }],
    queryFn: async () =>
      (await api.get<Page<WorkLog>>("/me/work-logs", { params: { date_from: weekStart, size: 500 } })).data,
  });
  const projectKey = new Map(projects.data?.items.map((p) => [p.id, p.key]));
  const weekHours = (weekLogs.data?.items ?? []).reduce((s, l) => s + num(l.hours), 0);
  const active = projects.data?.items.filter((p) => p.status === "active") ?? [];

  return (
    <>
      <PageHeader
        title={`Xin chào, ${me?.full_name.split(" ").pop()}`}
        description="Tổng quan công việc của bạn"
        actions={
          <Button variant="primary" icon={<Clock className="size-4" />} onClick={() => setLogOpen(true)}>
            Ghi log công việc
          </Button>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Dự án tham gia" value={projects.data?.total ?? "—"} />
        <Stat label="Dự án đang chạy" value={active.length} />
        <Stat label="Giờ đã log tuần này" value={fmtHours(weekHours)} sub={`Từ ${fmtDate(weekStart)}`} />
        <Stat label="Số lần log tuần này" value={weekLogs.data?.total ?? "—"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader
            title="Dự án của tôi"
            action={
              <Link href="/projects" className="text-[13px] font-medium text-brand hover:underline">
                Xem tất cả
              </Link>
            }
          />
          {projects.isPending ? (
            <Spinner />
          ) : !projects.data?.items.length ? (
            <Empty title="Bạn chưa tham gia dự án nào" description="Liên hệ quản lý dự án để được thêm vào." />
          ) : (
            <ul className="divide-y divide-line">
              {projects.data.items.slice(0, 8).map((p) => (
                <li key={p.id}>
                  <Link
                    href={`/projects/${p.id}`}
                    className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-subtle/60"
                  >
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-xs font-bold text-brand">
                      {p.key.slice(0, 3)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{p.name}</p>
                      <p className="truncate text-xs text-ink-3">
                        {p.key} · bắt đầu {fmtDate(p.start_date)}
                      </p>
                    </div>
                    <MetaBadge meta={PROJECT_STATUS[p.status]} />
                    <ArrowRight className="size-4 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader
            title="Log tuần này"
            action={
              <Link href="/timesheet" className="text-[13px] font-medium text-brand hover:underline">
                Timesheet
              </Link>
            }
          />
          {weekLogs.isPending ? (
            <Spinner />
          ) : !weekLogs.data?.items.length ? (
            <Empty
              title="Chưa có log nào tuần này"
              action={
                <Button size="sm" icon={<Plus className="size-4" />} onClick={() => setLogOpen(true)}>
                  Ghi log
                </Button>
              }
            />
          ) : (
            <ul className="divide-y divide-line">
              {weekLogs.data.items.slice(0, 10).map((l) => (
                <li key={l.id} className="flex items-start gap-3 px-4 py-2.5">
                  <span className="w-11 shrink-0 font-semibold tabular-nums">{fmtHours(l.hours)}</span>
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-1">
                      <span className="truncate">{withoutImages(l.description)}</span>
                      <TextImagesButton pid={l.project_id} text={l.description} />
                    </p>
                    <p className="text-xs text-ink-3">
                      {projectKey.get(l.project_id) ?? `#${l.project_id}`} · {fmtDate(l.log_date)} ·{" "}
                      {ACTIVITY_TYPE[l.activity_type]}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {logOpen && <WorkLogModal open onClose={() => setLogOpen(false)} />}
    </>
  );
}
