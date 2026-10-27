"use client";

import { useQuery } from "@tanstack/react-query";
import { addDays, addWeeks, format, isToday, parseISO, startOfWeek } from "date-fns";
import { vi } from "date-fns/locale";
import { ChevronLeft, ChevronRight, Clock, ImageIcon, Paperclip } from "lucide-react";
import { useState } from "react";

import { WorkLogModal } from "@/components/project/work-log-form";
import { inlineFileNames, inlineImageNames, withoutImages } from "@/components/text-images";
import { Button, IconButton } from "@/components/ui/button";
import { ExpandableText } from "@/components/ui/expandable-text";
import { Card, CardHeader, Empty, PageHeader, Spinner, Table } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { useProjects } from "@/lib/hooks";
import { ACTIVITY_TYPE } from "@/lib/labels";
import type { Page, WorkLog } from "@/lib/types";
import { cn, fmtDate, fmtHours, num } from "@/lib/utils";

const DAILY_TARGET = 8;

export default function TimesheetPage() {
  const [weekOffset, setWeekOffset] = useState(0);
  const [logOpen, setLogOpen] = useState(false);
  const [editing, setEditing] = useState<WorkLog | null>(null);
  const projects = useProjects();

  const start = addWeeks(startOfWeek(new Date(), { weekStartsOn: 1 }), weekOffset);
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  const from = format(days[0], "yyyy-MM-dd");
  const to = format(days[6], "yyyy-MM-dd");

  const logs = useQuery({
    queryKey: ["me", "work-logs", { from, to }],
    queryFn: async () =>
      (await api.get<Page<WorkLog>>("/me/work-logs", { params: { date_from: from, date_to: to, size: 500 } })).data.items,
  });

  const projectName = new Map(projects.data?.items.map((p) => [p.id, `${p.key} · ${p.name}`]));
  const rows = new Map<number, Map<string, number>>();
  for (const l of logs.data ?? []) {
    const row = rows.get(l.project_id) ?? new Map<string, number>();
    row.set(l.log_date, (row.get(l.log_date) ?? 0) + num(l.hours));
    rows.set(l.project_id, row);
  }
  const dayTotal = (d: string) => [...rows.values()].reduce((s, r) => s + (r.get(d) ?? 0), 0);
  const weekTotal = (logs.data ?? []).reduce((s, l) => s + num(l.hours), 0);

  return (
    <>
      <PageHeader
        title="Timesheet của tôi"
        description="Giờ làm theo tuần trên mọi dự án"
        actions={
          <Button variant="primary" icon={<Clock className="size-4" />} onClick={() => setLogOpen(true)}>
            Ghi log
          </Button>
        }
      />

      <Card className="mb-6">
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
          <IconButton label="Tuần trước" onClick={() => setWeekOffset((w) => w - 1)}>
            <ChevronLeft className="size-4" />
          </IconButton>
          <span className="min-w-48 text-center text-sm font-semibold tabular-nums">
            {fmtDate(days[0])} – {fmtDate(days[6])}
          </span>
          <IconButton label="Tuần sau" disabled={weekOffset >= 0} onClick={() => setWeekOffset((w) => w + 1)}>
            <ChevronRight className="size-4" />
          </IconButton>
          {weekOffset !== 0 && (
            <Button size="sm" variant="ghost" onClick={() => setWeekOffset(0)}>
              Tuần này
            </Button>
          )}
          <span className="ml-auto text-sm text-ink-3">
            Tổng tuần: <span className="font-semibold text-ink">{fmtHours(weekTotal)}</span>
          </span>
        </div>
        {logs.isPending ? (
          <Spinner />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Dự án</th>
                {days.map((d) => (
                  <th key={d.toISOString()} className={cn("text-center", isToday(d) && "!text-brand")}>
                    <span className="block capitalize">{format(d, "EEE", { locale: vi })}</span>
                    <span className="font-normal">{format(d, "dd/MM")}</span>
                  </th>
                ))}
                <th className="text-right">Tổng</th>
              </tr>
            </thead>
            <tbody>
              {rows.size === 0 && (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-ink-3">
                    Chưa có log nào trong tuần.
                  </td>
                </tr>
              )}
              {[...rows.entries()].map(([pid, row]) => (
                <tr key={pid}>
                  <td className="font-medium">{projectName.get(pid) ?? `Dự án #${pid}`}</td>
                  {days.map((d) => {
                    const h = row.get(format(d, "yyyy-MM-dd"));
                    return (
                      <td key={d.toISOString()} className="text-center tabular-nums">
                        {h ? fmtHours(h) : <span className="text-ink-3/50">·</span>}
                      </td>
                    );
                  })}
                  <td className="text-right font-semibold tabular-nums">
                    {fmtHours([...row.values()].reduce((a, b) => a + b, 0))}
                  </td>
                </tr>
              ))}
              {rows.size > 0 && (
                <tr className="bg-subtle/50 font-semibold">
                  <td>Tổng ngày</td>
                  {days.map((d) => {
                    const t = dayTotal(format(d, "yyyy-MM-dd"));
                    const weekend = d.getDay() === 0 || d.getDay() === 6;
                    return (
                      <td
                        key={d.toISOString()}
                        className={cn(
                          "text-center tabular-nums",
                          !weekend && t > 0 && t < DAILY_TARGET && "text-amber-700",
                          t > DAILY_TARGET && "text-violet-700",
                        )}
                      >
                        {t ? fmtHours(t) : "—"}
                      </td>
                    );
                  })}
                  <td className="text-right tabular-nums">{fmtHours(weekTotal)}</td>
                </tr>
              )}
            </tbody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader title="Chi tiết log trong tuần" />
        {!logs.data?.length ? (
          <Empty title="Không có log" />
        ) : (
          <ul className="divide-y divide-line">
            {[...logs.data]
              .sort((a, b) => b.log_date.localeCompare(a.log_date))
              .map((l) => (
                <li key={l.id}>
                  <button
                    type="button"
                    onClick={() => setEditing(l)}
                    className="flex w-full items-start gap-4 px-4 py-2.5 text-left text-sm hover:bg-subtle/60"
                  >
                    <span className="w-20 shrink-0 text-ink-3 tabular-nums">
                      {format(parseISO(l.log_date), "EEE dd/MM", { locale: vi })}
                    </span>
                    <span className="w-12 shrink-0 font-semibold tabular-nums">{fmtHours(l.hours)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-start gap-1">
                        <ExpandableText className="flex-1" text={withoutImages(l.description)} />
                        {inlineImageNames(l.description).length > 0 && (
                          <ImageIcon className="size-3.5 shrink-0 text-ink-3" aria-label="Có ảnh" />
                        )}
                        {inlineFileNames(l.description).length > 0 && (
                          <Paperclip className="size-3.5 shrink-0 text-ink-3" aria-label="Có file đính kèm" />
                        )}
                      </span>
                      <span className="text-xs text-ink-3">
                        {projectName.get(l.project_id) ?? `#${l.project_id}`} · {ACTIVITY_TYPE[l.activity_type]}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
          </ul>
        )}
      </Card>

      {logOpen && <WorkLogModal open onClose={() => setLogOpen(false)} />}
      {editing && <WorkLogModal open log={editing} onClose={() => setEditing(null)} />}
    </>
  );
}
