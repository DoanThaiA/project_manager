"use client";

import { useQuery } from "@tanstack/react-query";
import { addMonths, format, isToday, parseISO } from "date-fns";
import { vi } from "date-fns/locale";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import { AttendanceCard, DayLabel, RecordBadges, fmtCredit, fmtMinutes, fmtTime } from "@/components/attendance";
import { Badge } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { Card, PageHeader, Spinner, Stat, Table } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { AttendanceMonth } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function MyAttendancePage() {
  const [offset, setOffset] = useState(0);
  const month = format(addMonths(new Date(), offset), "yyyy-MM");

  const data = useQuery({
    queryKey: ["attendance", "me", month],
    queryFn: async () => (await api.get<AttendanceMonth>("/attendance/me/records", { params: { month } })).data,
  });
  const m = data.data;

  return (
    <>
      <PageHeader
        title="Chấm công của tôi"
        description={`${m ? `Ca: ${m.shift.name} · ` : ""}Giờ vào / giờ về theo ngày; chỉ chấm được khi dùng mạng công ty`}
      />

      {offset === 0 && <AttendanceCard />}

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        <Stat label="Công" value={m ? fmtCredit(m.credit) : "—"} sub={m && `chuẩn ${fmtCredit(m.expected_credit)}`} />
        <Stat label="Ngày có mặt" value={m?.present_days ?? "—"} />
        <Stat label="Đi muộn" value={m?.late_count ?? "—"} sub="lần" />
        <Stat label="Về sớm" value={m?.early_leave_count ?? "—"} sub="lần" />
        <Stat label="Thiếu check-out" value={m?.missing_checkout_count ?? "—"} />
        <Stat label="Vắng" value={m?.absent_days ?? "—"} sub="ngày làm việc" />
        <Stat label="Tổng giờ làm" value={m ? fmtMinutes(m.worked_minutes) : "—"} />
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
          <IconButton label="Tháng trước" onClick={() => setOffset((o) => o - 1)}>
            <ChevronLeft className="size-4" />
          </IconButton>
          <span className="min-w-32 text-center text-sm font-semibold capitalize tabular-nums">
            {format(addMonths(new Date(), offset), "LLLL yyyy", { locale: vi })}
          </span>
          <IconButton label="Tháng sau" disabled={offset >= 0} onClick={() => setOffset((o) => o + 1)}>
            <ChevronRight className="size-4" />
          </IconButton>
          {offset !== 0 && (
            <Button size="sm" variant="ghost" onClick={() => setOffset(0)}>
              Tháng này
            </Button>
          )}
        </div>
        {data.isPending ? (
          <Spinner />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Ngày</th>
                <th>Giờ vào</th>
                <th>Giờ về</th>
                <th>Giờ làm</th>
                <th>Công</th>
                <th>Trạng thái</th>
              </tr>
            </thead>
            <tbody>
              {(m?.days ?? [])
                .filter((d) => d.is_work_day || d.record)
                .map((d) => {
                  const day = parseISO(d.date);
                  return (
                    <tr key={d.date} className={cn(isToday(day) && "bg-brand-soft/40")}>
                      <td>
                        <DayLabel date={d.date} />
                      </td>
                      <td className="tabular-nums">{fmtTime(d.record?.check_in_at)}</td>
                      <td className="tabular-nums">{fmtTime(d.record?.check_out_at)}</td>
                      <td className="tabular-nums">{fmtMinutes(d.record?.worked_minutes)}</td>
                      <td className="tabular-nums">{d.record ? fmtCredit(d.record.credit) : "—"}</td>
                      <td>
                        {d.record ? (
                          <RecordBadges record={d.record} />
                        ) : d.absent ? (
                          <Badge tone="red">Vắng</Badge>
                        ) : (
                          <span className="text-ink-3">—</span>
                        )}
                        {d.record && !d.is_work_day && (
                          <Badge tone="violet" className="ml-1">
                            Ngoài ngày làm việc
                          </Badge>
                        )}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
