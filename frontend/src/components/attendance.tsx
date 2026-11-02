"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { LogIn, LogOut, Wifi, WifiOff } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Spinner } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { AttendanceRecord, AttendanceShiftDay, AttendanceToday } from "@/lib/types";
import { cn } from "@/lib/utils";

/** "2026-11-02T08:11:03+07:00" -> "08:11". */
export function fmtTime(v?: string | null) {
  return v ? format(parseISO(v), "HH:mm") : "—";
}

/** "08:00:00" -> "08:00". */
export function fmtClock(v: string) {
  return v.slice(0, 5);
}

/** 475 -> "7h55", 11 -> "11 phút". */
export function fmtMinutes(m?: number | null) {
  if (m === null || m === undefined) return "—";
  if (m < 60) return `${m} phút`;
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}`;
}

/** 0.5 -> "0,5". */
export function fmtCredit(v?: number | null) {
  return (v ?? 0).toLocaleString("vi-VN", { maximumFractionDigits: 2 });
}

const WEEKDAY_LABEL = ["", "T2", "T3", "T4", "T5", "T6", "T7", "CN"];

/** Lịch của ca, gộp các thứ liền nhau cùng giờ: "T2–T6 08:00–17:30 · T7 08:00–12:00". */
export function fmtSchedule(days: AttendanceShiftDay[]) {
  const key = (d: AttendanceShiftDay) => `${fmtClock(d.start_time)}–${fmtClock(d.end_time)}`;
  const groups: { from: number; to: number; hours: string }[] = [];
  for (const d of [...days].sort((a, b) => a.weekday - b.weekday)) {
    const last = groups.at(-1);
    if (last && last.hours === key(d) && last.to === d.weekday - 1) last.to = d.weekday;
    else groups.push({ from: d.weekday, to: d.weekday, hours: key(d) });
  }
  return groups
    .map((g) => `${WEEKDAY_LABEL[g.from]}${g.to > g.from ? `–${WEEKDAY_LABEL[g.to]}` : ""} ${g.hours}`)
    .join(" · ");
}

export function RecordBadges({ record }: { record: AttendanceRecord }) {
  const ok = !record.is_late && !record.is_early_leave && !record.missing_checkout;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {record.is_late && <Badge tone="amber">Muộn {fmtMinutes(record.late_minutes)}</Badge>}
      {record.is_early_leave && <Badge tone="orange">Về sớm {fmtMinutes(record.early_leave_minutes)}</Badge>}
      {record.missing_checkout && <Badge tone="red">Thiếu check-out</Badge>}
      {ok && <Badge tone="green">Đúng giờ</Badge>}
      {record.source === "admin" && (
        <span title={record.adjusted_reason ?? undefined}>
          <Badge tone="gray">Đã chỉnh</Badge>
        </span>
      )}
    </span>
  );
}

/** Thẻ chấm công trên trang Tổng quan: check-in / check-out từ mạng công ty. */
export function AttendanceCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const today = useQuery({
    queryKey: ["attendance", "today"],
    queryFn: async () => (await api.get<AttendanceToday>("/attendance/me/today")).data,
    refetchOnWindowFocus: true, // đổi Wi-Fi rồi quay lại tab: cập nhật trạng thái mạng
  });
  const punch = useMutation({
    mutationFn: async (action: "check-in" | "check-out") =>
      (await api.post<AttendanceRecord>(`/attendance/${action}`)).data,
    onSuccess: (record, action) => {
      toast.success(
        action === "check-in" ? `Đã check-in lúc ${fmtTime(record.check_in_at)}` : `Đã check-out lúc ${fmtTime(record.check_out_at)}`,
      );
      qc.invalidateQueries({ queryKey: ["attendance"] });
    },
    onError: (e) => {
      toast.error(e);
      qc.invalidateQueries({ queryKey: ["attendance", "today"] });
    },
  });

  const data = today.data;
  const record = data?.record;
  return (
    <Card className="mb-6">
      <CardHeader
        title={data ? `Chấm công hôm nay · ${data.shift.name}` : "Chấm công hôm nay"}
        action={
          <Link href="/attendance" className="text-[13px] font-medium text-brand hover:underline">
            Lịch công
          </Link>
        }
      />
      {today.isPending ? (
        <Spinner />
      ) : !data ? (
        <p className="px-4 py-4 text-sm text-ink-3">Không tải được trạng thái chấm công.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-4 px-4 py-4">
          <div className="grid min-w-0 flex-1 grid-cols-2 gap-4 sm:max-w-sm">
            <div>
              <p className="text-[13px] text-ink-3">
                Giờ vào · {data.schedule ? `ca ${fmtClock(data.schedule.start_time)}` : "ngày nghỉ"}
              </p>
              <p className="text-2xl font-semibold tabular-nums">{fmtTime(record?.check_in_at)}</p>
            </div>
            <div>
              <p className="text-[13px] text-ink-3">
                Giờ về · {data.schedule ? `ca ${fmtClock(data.schedule.end_time)}` : "ngày nghỉ"}
              </p>
              <p className="text-2xl font-semibold tabular-nums">{fmtTime(record?.check_out_at)}</p>
            </div>
            {record && (
              <div className="col-span-2">
                <RecordBadges record={record} />
              </div>
            )}
          </div>

          <div className="flex w-full flex-col gap-2 sm:w-auto sm:items-end">
            <div className="flex gap-2">
              <Button
                variant="primary"
                className="h-11 flex-1 px-5 sm:flex-none"
                icon={<LogIn className="size-4" />}
                disabled={!data.can_check_in}
                loading={punch.isPending && punch.variables === "check-in"}
                onClick={() => punch.mutate("check-in")}
              >
                Check-in
              </Button>
              <Button
                className="h-11 flex-1 px-5 sm:flex-none"
                icon={<LogOut className="size-4" />}
                disabled={!data.can_check_out}
                loading={punch.isPending && punch.variables === "check-out"}
                onClick={() => punch.mutate("check-out")}
              >
                Check-out
              </Button>
            </div>
            <p
              className={cn(
                "flex items-center gap-1.5 text-xs",
                data.network ? "text-ink-3" : "rounded-md bg-amber-50 px-2 py-1 text-amber-800",
              )}
            >
              {data.network ? <Wifi className="size-3.5" /> : <WifiOff className="size-3.5" />}
              {data.network
                ? `Mạng: ${data.network.name} · IP ${data.ip}`
                : `Không ở mạng công ty (IP ${data.ip ?? "không xác định"}) — kết nối Wi-Fi văn phòng để chấm công`}
            </p>
          </div>
        </div>
      )}
    </Card>
  );
}
