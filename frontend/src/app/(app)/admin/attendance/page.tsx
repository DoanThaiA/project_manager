"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { endOfMonth, format, parseISO } from "date-fns";
import { vi } from "date-fns/locale";
import { Download, Pencil, Plus, Star, Trash2, Wifi } from "lucide-react";
import { useState } from "react";

import { RecordBadges, fmtClock, fmtCredit, fmtMinutes, fmtSchedule, fmtTime } from "@/components/attendance";
import { Badge } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/form";
import { Card, Empty, PageHeader, Pagination, Spinner, Table, UserChip } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api, clean } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type {
  AttendanceEvent,
  AttendanceNetwork,
  AttendanceRecord,
  AttendanceShift,
  AttendanceSummary,
  MyIp,
  Page,
  UserBrief,
} from "@/lib/types";
import { cn, fmtDateTime } from "@/lib/utils";

type Tab = "records" | "summary" | "shifts" | "networks" | "events";

const FLAGS = { late: "Đi muộn", early_leave: "Về sớm", missing_checkout: "Thiếu check-out" } as const;
const REASONS: Record<string, string> = {
  outside_network: "Ngoài mạng công ty",
  not_checked_in: "Check-out khi chưa check-in",
  api_token: "Dùng token PAT",
};

const WEEKDAYS: [number, string][] = [
  [1, "T2"],
  [2, "T3"],
  [3, "T4"],
  [4, "T5"],
  [5, "T6"],
  [6, "T7"],
  [7, "CN"],
];

function useShifts() {
  return useQuery({
    queryKey: ["attendance", "shifts"],
    queryFn: async () => (await api.get<AttendanceShift[]>("/attendance/shifts")).data,
  });
}

/** Người phải chấm công trong tháng (dùng cho bộ lọc / chọn người khi thêm công). */
function useSummary(month: string) {
  return useQuery({
    queryKey: ["attendance", "summary", month],
    queryFn: async () => (await api.get<AttendanceSummary>("/attendance/summary", { params: { month } })).data,
  });
}

export default function AttendanceAdminPage() {
  const { can } = useAuth();
  const manage = can("attendance.manage");
  const [tab, setTab] = useState<Tab>("records");
  const [month, setMonth] = useState(() => format(new Date(), "yyyy-MM"));
  const summary = useSummary(month);
  const shifts = useShifts();
  const users = summary.data?.rows.map((r) => r.user) ?? [];

  const tabs: [Tab, string][] = [
    ["records", "Bảng công"],
    ["summary", "Tổng hợp tháng"],
    ...(manage
      ? ([
          ["shifts", "Ca làm việc"],
          ["networks", "Mạng công ty"],
          ["events", "Lần bị từ chối"],
        ] as [Tab, string][])
      : []),
  ];

  return (
    <>
      <PageHeader
        title="Chấm công"
        description="Chấm công theo IP mạng công ty, theo ca của từng nhân viên"
        actions={
          (tab === "records" || tab === "summary") && (
            <Input
              type="month"
              aria-label="Tháng"
              className="w-40"
              value={month}
              max={format(new Date(), "yyyy-MM")}
              onChange={(e) => e.target.value && setMonth(e.target.value)}
            />
          )
        }
      />
      <Card>
        <div className="flex items-center gap-1 overflow-x-auto border-b border-line px-3 pt-2" role="tablist">
          {tabs.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-[13px] font-medium whitespace-nowrap transition-colors",
                tab === key ? "border-brand text-brand" : "border-transparent text-ink-3 hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {tab === "records" && (
          <RecordsTab month={month} users={users} shifts={shifts.data ?? []} manage={manage} />
        )}
        {tab === "summary" && <SummaryTab month={month} data={summary.data} loading={summary.isPending} />}
        {tab === "shifts" && manage && (
          <ShiftsTab shifts={shifts.data} rows={summary.data?.rows ?? []} loading={shifts.isPending} />
        )}
        {tab === "networks" && manage && <NetworksTab />}
        {tab === "events" && manage && <EventsTab />}
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- Bảng công

function RecordsTab({
  month,
  users,
  shifts,
  manage,
}: {
  month: string;
  users: UserBrief[];
  shifts: AttendanceShift[];
  manage: boolean;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [userId, setUserId] = useState("");
  const [flag, setFlag] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<AttendanceRecord | "new" | null>(null);
  const from = `${month}-01`;
  const to = format(endOfMonth(parseISO(from)), "yyyy-MM-dd");
  const params = clean({ from, to, user_id: userId, flag, page, size: 50 });

  const records = useQuery({
    queryKey: ["attendance", "records", params],
    queryFn: async () => (await api.get<Page<AttendanceRecord>>("/attendance/records", { params })).data,
    placeholderData: keepPreviousData,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/attendance/records/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["attendance"] });
      toast.success("Đã xoá bản ghi chấm công");
    },
    onError: toast.error,
  });

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
        <Select
          aria-label="Nhân viên"
          className="w-56"
          value={userId}
          onChange={(e) => {
            setUserId(e.target.value);
            setPage(1);
          }}
        >
          <option value="">Tất cả nhân viên</option>
          {users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Trạng thái"
          className="w-44"
          value={flag}
          onChange={(e) => {
            setFlag(e.target.value);
            setPage(1);
          }}
        >
          <option value="">Mọi trạng thái</option>
          {Object.entries(FLAGS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </Select>
        {manage && (
          <Button
            size="sm"
            variant="primary"
            className="ml-auto"
            icon={<Plus className="size-4" />}
            onClick={() => setEditing("new")}
          >
            Thêm công
          </Button>
        )}
      </div>
      {records.isPending ? (
        <Spinner />
      ) : !records.data?.items.length ? (
        <Empty title="Không có bản ghi chấm công" description="Thử đổi tháng hoặc bộ lọc." />
      ) : (
        <>
          <Table>
            <thead>
              <tr>
                <th>Ngày</th>
                <th>Nhân viên</th>
                <th>Ca</th>
                <th>Vào</th>
                <th>Về</th>
                <th>Giờ làm</th>
                <th>Công</th>
                <th>Trạng thái</th>
                <th>Mạng / IP vào</th>
                {manage && <th className="w-20" />}
              </tr>
            </thead>
            <tbody>
              {records.data.items.map((r) => (
                <tr key={r.id}>
                  <td className="whitespace-nowrap">
                    <span className="inline-block w-9 text-ink-3 capitalize">
                      {format(parseISO(r.work_date), "EEE", { locale: vi })}
                    </span>
                    {format(parseISO(r.work_date), "dd/MM")}
                  </td>
                  <td>
                    <UserChip id={r.user_id} name={r.user?.full_name} />
                  </td>
                  <td className="whitespace-nowrap text-ink-2">{r.shift?.name}</td>
                  <td className="tabular-nums">{fmtTime(r.check_in_at)}</td>
                  <td className="tabular-nums">{fmtTime(r.check_out_at)}</td>
                  <td className="tabular-nums">{fmtMinutes(r.worked_minutes)}</td>
                  <td className="tabular-nums">{fmtCredit(r.credit)}</td>
                  <td>
                    <RecordBadges record={r} />
                  </td>
                  <td className="text-xs text-ink-3">
                    {r.check_in_network?.name ?? (r.source === "admin" ? "Quản lý thêm" : "—")}
                    {r.check_in_ip && <span className="block tabular-nums">{r.check_in_ip}</span>}
                  </td>
                  {manage && (
                    <td>
                      <div className="flex justify-end gap-0.5">
                        <IconButton label="Sửa giờ" onClick={() => setEditing(r)}>
                          <Pencil className="size-4" />
                        </IconButton>
                        <IconButton
                          label="Xoá"
                          onClick={() =>
                            confirm(`Xoá công ngày ${format(parseISO(r.work_date), "dd/MM")} của ${r.user?.full_name}?`) &&
                            remove.mutate(r.id)
                          }
                        >
                          <Trash2 className="size-4" />
                        </IconButton>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </Table>
          <Pagination page={page} size={50} total={records.data.total} onChange={setPage} />
        </>
      )}
      {editing && (
        <RecordModal
          record={editing === "new" ? undefined : editing}
          users={users}
          shifts={shifts}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  );
}

function RecordModal({
  record,
  users,
  shifts,
  onClose,
}: {
  record?: AttendanceRecord;
  users: UserBrief[];
  shifts: AttendanceShift[];
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const editing = !!record;
  const [form, setForm] = useState({
    user_id: record ? String(record.user_id) : "",
    work_date: record?.work_date ?? format(new Date(), "yyyy-MM-dd"),
    check_in_time: record ? fmtTime(record.check_in_at) : "08:00",
    check_out_time: record?.check_out_at ? fmtTime(record.check_out_at) : "",
    shift_id: record ? String(record.shift_id) : "", // "" = ca hiện tại của nhân viên
    note: record?.note ?? "",
    adjusted_reason: "",
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));

  const save = useMutation({
    mutationFn: async () => {
      const times = {
        check_in_time: form.check_in_time,
        check_out_time: form.check_out_time || null,
        shift_id: form.shift_id ? Number(form.shift_id) : null,
        note: form.note || null,
        adjusted_reason: form.adjusted_reason.trim(),
      };
      if (editing) return api.patch(`/attendance/records/${record.id}`, times);
      return api.post("/attendance/records", { ...times, user_id: Number(form.user_id), work_date: form.work_date });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["attendance"] });
      toast.success(editing ? "Đã sửa công" : "Đã thêm công");
      onClose();
    },
    onError: toast.error,
  });
  const valid =
    form.check_in_time &&
    form.adjusted_reason.trim().length >= 3 &&
    (editing || (form.user_id && form.work_date)) &&
    (!form.check_out_time || form.check_out_time >= form.check_in_time);

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={editing ? `Sửa công · ${record.user?.full_name}` : "Thêm công"}
      description={editing ? format(parseISO(record.work_date), "EEEE dd/MM/yyyy", { locale: vi }) : "Cho ngày nhân viên quên chấm"}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button variant="primary" loading={save.isPending} disabled={!valid} onClick={() => save.mutate()}>
            Lưu
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {!editing && (
          <>
            <Field label="Nhân viên" required className="sm:col-span-2">
              {(id) => (
                <Select id={id} value={form.user_id} onChange={(e) => set("user_id", e.target.value)}>
                  <option value="">Chọn nhân viên</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name} ({u.username})
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Ngày" required className="sm:col-span-2">
              {(id) => (
                <Input
                  id={id}
                  type="date"
                  value={form.work_date}
                  max={format(new Date(), "yyyy-MM-dd")}
                  onChange={(e) => set("work_date", e.target.value)}
                />
              )}
            </Field>
          </>
        )}
        <Field label="Ca" className="sm:col-span-2" hint="Tính đi muộn / về sớm theo ca này">
          {(id) => (
            <Select id={id} value={form.shift_id} onChange={(e) => set("shift_id", e.target.value)}>
              {!editing && <option value="">Ca hiện tại của nhân viên</option>}
              {shifts.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Giờ vào" required>
          {(id) => (
            <Input id={id} type="time" value={form.check_in_time} onChange={(e) => set("check_in_time", e.target.value)} />
          )}
        </Field>
        <Field label="Giờ về" hint="Để trống = chưa check-out">
          {(id) => (
            <Input id={id} type="time" value={form.check_out_time} onChange={(e) => set("check_out_time", e.target.value)} />
          )}
        </Field>
        <Field label="Ghi chú" className="sm:col-span-2">
          {(id) => <Input id={id} value={form.note} onChange={(e) => set("note", e.target.value)} />}
        </Field>
        <Field label="Lý do chỉnh công" required hint="Ghi vào nhật ký hệ thống" className="sm:col-span-2">
          {(id) => (
            <Textarea
              id={id}
              rows={2}
              value={form.adjusted_reason}
              placeholder="VD: Quên check-out, đã xác nhận với quản lý"
              onChange={(e) => set("adjusted_reason", e.target.value)}
            />
          )}
        </Field>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- Tổng hợp

function SummaryTab({ month, data, loading }: { month: string; data?: AttendanceSummary; loading: boolean }) {
  const toast = useToast();
  const [downloading, setDownloading] = useState(false);

  async function download() {
    setDownloading(true);
    try {
      const res = await api.get<Blob>("/attendance/summary/export", { params: { month }, responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `cham-cong-${month}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e);
    } finally {
      setDownloading(false);
    }
  }

  if (loading) return <Spinner />;
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3 text-sm text-ink-3">
        <span>{data?.rows.length ?? 0} nhân viên · ngày làm việc / vắng tính theo ca của từng người</span>
        <Button
          size="sm"
          className="ml-auto"
          icon={<Download className="size-4" />}
          loading={downloading}
          disabled={!data?.rows.length}
          onClick={download}
        >
          Tải CSV (Excel)
        </Button>
      </div>
      {!data?.rows.length ? (
        <Empty title="Chưa có nhân viên nào phải chấm công" description="Gán vai trò có quyền attendance.checkin (vd STAFF)." />
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Nhân viên</th>
              <th>Ca</th>
              <th className="text-right">Có mặt</th>
              <th className="text-right">Vắng</th>
              <th className="text-right">Đi muộn</th>
              <th className="text-right">Về sớm</th>
              <th className="text-right">Thiếu check-out</th>
              <th className="text-right">Giờ làm</th>
              <th className="text-right">Công</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.user.id}>
                <td>
                  <UserChip id={r.user.id} name={r.user.full_name} />
                </td>
                <td className="whitespace-nowrap text-ink-2">{r.shift.name}</td>
                <td className="text-right tabular-nums">
                  {r.present_days}
                  <span className="text-ink-3">/{r.work_days}</span>
                </td>
                <td className={cn("text-right tabular-nums", r.absent_days > 0 && "font-semibold text-red-700")}>
                  {r.absent_days}
                </td>
                <td className="text-right tabular-nums">
                  {r.late_count}
                  {r.late_count > 0 && <span className="block text-xs text-ink-3">{fmtMinutes(r.late_minutes)}</span>}
                </td>
                <td className="text-right tabular-nums">
                  {r.early_leave_count}
                  {r.early_leave_count > 0 && (
                    <span className="block text-xs text-ink-3">{fmtMinutes(r.early_leave_minutes)}</span>
                  )}
                </td>
                <td className="text-right tabular-nums">{r.missing_checkout_count}</td>
                <td className="text-right tabular-nums">{fmtMinutes(r.worked_minutes)}</td>
                <td className="text-right font-semibold tabular-nums">
                  {fmtCredit(r.credit)}
                  <span className="font-normal text-ink-3">/{fmtCredit(r.expected_credit)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </>
  );
}

// ---------------------------------------------------------------- Ca làm việc

function ShiftsTab({
  shifts,
  rows,
  loading,
}: {
  shifts?: AttendanceShift[];
  rows: AttendanceSummary["rows"];
  loading: boolean;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState<AttendanceShift | "new" | null>(null);
  const defaultShift = shifts?.find((s) => s.is_default);
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/attendance/shifts/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["attendance"] });
      toast.success("Đã xoá ca");
    },
    onError: toast.error,
  });
  const assign = useMutation({
    mutationFn: ({ userId, shiftId }: { userId: number; shiftId: number | null }) =>
      api.put(`/attendance/users/${userId}/shift`, { shift_id: shiftId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["attendance"] });
      toast.success("Đã gán ca");
    },
    onError: toast.error,
  });

  if (loading) return <Spinner />;
  return (
    <>
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <p className="text-sm text-ink-3">Sửa ca chỉ áp dụng cho lần chấm sau; công đã chấm giữ cách tính cũ.</p>
        <Button
          size="sm"
          variant="primary"
          className="ml-auto"
          icon={<Plus className="size-4" />}
          onClick={() => setEditing("new")}
        >
          Thêm ca
        </Button>
      </div>
      <Table>
        <thead>
          <tr>
            <th>Ca</th>
            <th>Lịch trong tuần</th>
            <th>Cho phép muộn</th>
            <th className="text-right">Số người gán</th>
            <th className="w-20" />
          </tr>
        </thead>
        <tbody>
          {(shifts ?? []).map((s) => (
            <tr key={s.id}>
              <td className="font-medium">
                {s.name}
                {s.is_default && (
                  <Badge tone="indigo" className="ml-2">
                    Mặc định
                  </Badge>
                )}
              </td>
              <td className="tabular-nums">{fmtSchedule(s.days)}</td>
              <td className="tabular-nums text-ink-2">{s.late_grace_minutes} phút</td>
              <td className="text-right tabular-nums">{s.user_count}</td>
              <td>
                <div className="flex justify-end gap-0.5">
                  <IconButton label="Sửa ca" onClick={() => setEditing(s)}>
                    <Pencil className="size-4" />
                  </IconButton>
                  {!s.is_default && (
                    <IconButton label="Xoá" onClick={() => confirm(`Xoá ca ${s.name}?`) && remove.mutate(s.id)}>
                      <Trash2 className="size-4" />
                    </IconButton>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>

      <div className="border-y border-line bg-subtle/60 px-4 py-2.5 text-[13px] font-semibold">Phân ca cho nhân viên</div>
      {!rows.length ? (
        <Empty title="Chưa có nhân viên nào phải chấm công" description="Gán vai trò có quyền attendance.checkin (vd STAFF)." />
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Nhân viên</th>
              <th className="w-72">Ca</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.user.id}>
                <td>
                  <UserChip id={r.user.id} name={r.user.full_name} />
                </td>
                <td>
                  <Select
                    aria-label={`Ca của ${r.user.full_name}`}
                    value={r.assigned_shift_id ?? ""}
                    disabled={assign.isPending}
                    onChange={(e) =>
                      assign.mutate({ userId: r.user.id, shiftId: e.target.value ? Number(e.target.value) : null })
                    }
                  >
                    <option value="">Mặc định ({defaultShift?.name ?? "—"})</option>
                    {(shifts ?? []).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name} · {fmtSchedule(s.days)}
                      </option>
                    ))}
                  </Select>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {editing && <ShiftModal shift={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

type DayForm = { on: boolean; start_time: string; end_time: string; break_start: string; break_end: string; credit: number };

const EMPTY_DAY: DayForm = { on: false, start_time: "08:00", end_time: "17:30", break_start: "", break_end: "", credit: 1 };

function dayValid(d: DayForm) {
  if (!d.on) return true;
  if (!(d.start_time < d.end_time) || !(d.credit > 0 && d.credit <= 1)) return false;
  if (!d.break_start && !d.break_end) return true;
  return !!d.break_start && !!d.break_end && d.start_time <= d.break_start && d.break_start < d.break_end && d.break_end <= d.end_time;
}

function ShiftModal({ shift, onClose }: { shift?: AttendanceShift; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const editing = !!shift;
  const [form, setForm] = useState({
    name: shift?.name ?? "",
    late_grace_minutes: shift?.late_grace_minutes ?? 5,
    early_grace_minutes: shift?.early_grace_minutes ?? 0,
    is_default: shift?.is_default ?? false,
  });
  // Lịch 7 ngày (T2 … CN); ca mới mặc định T2 – T6 08:00 – 17:30, nghỉ trưa 12:00 – 13:30
  const [days, setDays] = useState<DayForm[]>(() =>
    WEEKDAYS.map(([w]) => {
      const d = shift?.days.find((x) => x.weekday === w);
      if (d) {
        return {
          on: true,
          start_time: fmtClock(d.start_time),
          end_time: fmtClock(d.end_time),
          break_start: d.break_start ? fmtClock(d.break_start) : "",
          break_end: d.break_end ? fmtClock(d.break_end) : "",
          credit: d.credit,
        };
      }
      return shift ? EMPTY_DAY : { ...EMPTY_DAY, on: w <= 5, break_start: "12:00", break_end: "13:30" };
    }),
  );
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));
  const setDay = (i: number, patch: Partial<DayForm>) => setDays((list) => list.map((d, j) => (j === i ? { ...d, ...patch } : d)));
  const copyMondayToWeekdays = () => setDays((list) => list.map((d, j) => (j >= 1 && j <= 4 ? { ...list[0] } : d)));

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        ...form,
        name: form.name.trim(),
        days: days.flatMap((d, i) =>
          d.on
            ? [
                {
                  weekday: WEEKDAYS[i][0],
                  start_time: d.start_time,
                  end_time: d.end_time,
                  break_start: d.break_start || null,
                  break_end: d.break_end || null,
                  credit: d.credit,
                },
              ]
            : [],
        ),
      };
      if (editing) await api.put(`/attendance/shifts/${shift.id}`, body);
      else await api.post("/attendance/shifts", body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["attendance"] });
      toast.success(editing ? "Đã lưu ca" : "Đã thêm ca");
      onClose();
    },
    onError: toast.error,
  });
  const valid = form.name.trim() && days.some((d) => d.on) && days.every(dayValid);

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={editing ? `Sửa ca ${shift.name}` : "Thêm ca làm việc"}
      description="Bỏ chọn “Làm” = ngày nghỉ của ca. Sửa ca chỉ áp dụng cho lần chấm sau."
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button variant="primary" loading={save.isPending} disabled={!valid} onClick={() => save.mutate()}>
            Lưu
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Tên ca" required>
          {(id) => <Input id={id} value={form.name} placeholder="VD: Ca sáng" onChange={(e) => set("name", e.target.value)} />}
        </Field>
        <Field label="Cho phép vào muộn (phút)">
          {(id) => (
            <Input
              id={id}
              type="number"
              min={0}
              max={240}
              value={form.late_grace_minutes}
              onChange={(e) => set("late_grace_minutes", Number(e.target.value))}
            />
          )}
        </Field>
        <Field label="Cho phép về sớm (phút)">
          {(id) => (
            <Input
              id={id}
              type="number"
              min={0}
              max={240}
              value={form.early_grace_minutes}
              onChange={(e) => set("early_grace_minutes", Number(e.target.value))}
            />
          )}
        </Field>
      </div>

      <div className="mt-5 mb-2 flex items-center justify-between">
        <p className="text-[13px] font-medium text-ink-2">Lịch trong tuần</p>
        <Button size="sm" variant="ghost" onClick={copyMondayToWeekdays}>
          Áp dụng giờ T2 cho T3–T6
        </Button>
      </div>
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-sm [&_td]:px-2 [&_td]:py-1.5 [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:text-xs [&_th]:font-medium [&_th]:text-ink-3">
          <thead className="bg-subtle/70">
            <tr>
              <th>Thứ</th>
              <th>Làm</th>
              <th>Giờ vào</th>
              <th>Giờ về</th>
              <th>Nghỉ trưa từ</th>
              <th>đến</th>
              <th>Công</th>
            </tr>
          </thead>
          <tbody>
            {days.map((d, i) => (
              <tr key={WEEKDAYS[i][0]} className={cn("border-t border-line", !dayValid(d) && "bg-red-50")}>
                <td className="font-medium">{WEEKDAYS[i][1]}</td>
                <td>
                  <Checkbox
                    label={<span className="sr-only">Làm việc {WEEKDAYS[i][1]}</span>}
                    checked={d.on}
                    onChange={(e) => setDay(i, { on: e.target.checked })}
                  />
                </td>
                {d.on ? (
                  <>
                    <td>
                      <Input type="time" aria-label={`Giờ vào ${WEEKDAYS[i][1]}`} className="w-28" value={d.start_time} onChange={(e) => setDay(i, { start_time: e.target.value })} />
                    </td>
                    <td>
                      <Input type="time" aria-label={`Giờ về ${WEEKDAYS[i][1]}`} className="w-28" value={d.end_time} onChange={(e) => setDay(i, { end_time: e.target.value })} />
                    </td>
                    <td>
                      <Input type="time" aria-label={`Nghỉ trưa từ ${WEEKDAYS[i][1]}`} className="w-28" value={d.break_start} onChange={(e) => setDay(i, { break_start: e.target.value })} />
                    </td>
                    <td>
                      <Input type="time" aria-label={`Nghỉ trưa đến ${WEEKDAYS[i][1]}`} className="w-28" value={d.break_end} onChange={(e) => setDay(i, { break_end: e.target.value })} />
                    </td>
                    <td>
                      <Select aria-label={`Số công ${WEEKDAYS[i][1]}`} className="w-20" value={d.credit} onChange={(e) => setDay(i, { credit: Number(e.target.value) })}>
                        <option value={1}>1</option>
                        <option value={0.5}>0,5</option>
                      </Select>
                    </td>
                  </>
                ) : (
                  <td colSpan={5} className="text-ink-3">
                    Nghỉ
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Checkbox
        className="mt-4"
        label={
          <span className="inline-flex items-center gap-1">
            <Star className="size-3.5" /> Ca mặc định (cho nhân viên chưa được gán ca)
          </span>
        }
        checked={form.is_default}
        disabled={shift?.is_default}
        onChange={(e) => set("is_default", e.target.checked)}
      />
    </Modal>
  );
}

// ---------------------------------------------------------------- Mạng công ty

function NetworksTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [adding, setAdding] = useState<"manual" | "current" | null>(null);
  const networks = useQuery({
    queryKey: ["attendance", "networks"],
    queryFn: async () => (await api.get<AttendanceNetwork[]>("/attendance/networks")).data,
  });
  const myIp = useQuery({
    queryKey: ["attendance", "my-ip"],
    queryFn: async () => (await api.get<MyIp>("/attendance/my-ip")).data,
  });
  const done = (text: string) => {
    qc.invalidateQueries({ queryKey: ["attendance"] });
    toast.success(text);
  };
  const toggle = useMutation({
    mutationFn: (n: AttendanceNetwork) => api.patch(`/attendance/networks/${n.id}`, { is_active: !n.is_active }),
    onSuccess: () => done("Đã cập nhật mạng"),
    onError: toast.error,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/attendance/networks/${id}`),
    onSuccess: () => done("Đã xoá mạng"),
    onError: toast.error,
  });

  return (
    <>
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0 flex-1 text-sm">
          <p className="flex items-center gap-1.5">
            <Wifi className="size-4 text-ink-3" />
            IP của bạn: <span className="font-semibold tabular-nums">{myIp.data?.ip ?? "…"}</span>
            {myIp.data &&
              (myIp.data.network ? (
                <Badge tone="green">Thuộc {myIp.data.network.name}</Badge>
              ) : (
                <Badge tone="amber">Chưa thuộc mạng nào</Badge>
              ))}
          </p>
          {myIp.data && (
            <p className="mt-0.5 text-xs text-ink-3">
              X-Forwarded-For: {myIp.data.x_forwarded_for ?? "—"} · kết nối từ {myIp.data.client_host ?? "—"}
            </p>
          )}
        </div>
        <Button size="sm" icon={<Wifi className="size-4" />} disabled={!!myIp.data?.network} onClick={() => setAdding("current")}>
          Thêm IP tôi đang dùng
        </Button>
        <Button size="sm" variant="primary" icon={<Plus className="size-4" />} onClick={() => setAdding("manual")}>
          Thêm mạng
        </Button>
      </div>
      {networks.isPending ? (
        <Spinner />
      ) : !networks.data?.length ? (
        <Empty
          title="Chưa khai báo mạng công ty"
          description="Chưa có mạng nào thì không ai chấm công được. Đứng ở văn phòng và bấm “Thêm IP tôi đang dùng”."
        />
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Tên</th>
              <th>IP / dải IP</th>
              <th>Ghi chú</th>
              <th>Đang bật</th>
              <th className="w-12" />
            </tr>
          </thead>
          <tbody>
            {networks.data.map((n) => (
              <tr key={n.id}>
                <td className="font-medium">{n.name}</td>
                <td className="font-mono text-[13px]">{n.cidr}</td>
                <td className="text-ink-3">{n.note ?? "—"}</td>
                <td>
                  <Checkbox
                    label={n.is_active ? "Bật" : "Tắt"}
                    checked={n.is_active}
                    disabled={toggle.isPending}
                    onChange={() => toggle.mutate(n)}
                  />
                </td>
                <td>
                  <IconButton
                    label="Xoá"
                    onClick={() => confirm(`Xoá mạng ${n.name} (${n.cidr})?`) && remove.mutate(n.id)}
                  >
                    <Trash2 className="size-4" />
                  </IconButton>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {adding && <NetworkModal fromCurrentIp={adding === "current"} ip={myIp.data?.ip} onClose={() => setAdding(null)} />}
    </>
  );
}

function NetworkModal({ fromCurrentIp, ip, onClose }: { fromCurrentIp: boolean; ip?: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({ name: "", cidr: "", note: "" });
  const save = useMutation({
    mutationFn: async () => {
      const body = { name: form.name.trim(), note: form.note || null };
      if (fromCurrentIp) await api.post("/attendance/networks/current-ip", body);
      else await api.post("/attendance/networks", { ...body, cidr: form.cidr.trim() });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["attendance"] });
      toast.success("Đã thêm mạng công ty");
      onClose();
    },
    onError: toast.error,
  });
  const valid = form.name.trim() && (fromCurrentIp || form.cidr.trim());

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={fromCurrentIp ? "Thêm IP tôi đang dùng" : "Thêm mạng công ty"}
      description={fromCurrentIp ? `IP ${ip ?? "?"} — chỉ bấm khi đang dùng mạng văn phòng` : undefined}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button variant="primary" loading={save.isPending} disabled={!valid} onClick={() => save.mutate()}>
            Thêm
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <Field label="Tên" required>
          {(id) => (
            <Input
              id={id}
              value={form.name}
              placeholder="VD: VP Hà Nội - Viettel"
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          )}
        </Field>
        {!fromCurrentIp && (
          <Field label="IP / dải IP" required hint="IP công cộng của văn phòng: 113.161.10.20, 113.161.10.16/29, 2402:800:1234::/56">
            {(id) => (
              <Input
                id={id}
                value={form.cidr}
                className="font-mono"
                onChange={(e) => setForm((f) => ({ ...f, cidr: e.target.value }))}
              />
            )}
          </Field>
        )}
        <Field label="Ghi chú">
          {(id) => <Input id={id} value={form.note} onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))} />}
        </Field>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- Lần bị từ chối

function EventsTab() {
  const [page, setPage] = useState(1);
  const events = useQuery({
    queryKey: ["attendance", "events", page],
    queryFn: async () =>
      (await api.get<Page<AttendanceEvent>>("/attendance/events", { params: { accepted: false, page, size: 50 } })).data,
    placeholderData: keepPreviousData,
  });

  if (events.isPending) return <Spinner />;
  if (!events.data?.items.length) return <Empty title="Chưa có lần chấm công nào bị từ chối" />;
  return (
    <>
      <Table>
        <thead>
          <tr>
            <th>Thời điểm</th>
            <th>Nhân viên</th>
            <th>Thao tác</th>
            <th>Lý do</th>
            <th>IP</th>
            <th>Trình duyệt</th>
          </tr>
        </thead>
        <tbody>
          {events.data.items.map((e) => (
            <tr key={e.id}>
              <td className="whitespace-nowrap tabular-nums">{fmtDateTime(e.created_at)}</td>
              <td>
                <UserChip id={e.user?.id} name={e.user?.full_name} />
              </td>
              <td>{e.action === "check_in" ? "Check-in" : "Check-out"}</td>
              <td>
                <Badge tone="amber">{REASONS[e.reason ?? ""] ?? e.reason}</Badge>
              </td>
              <td className="font-mono text-[13px]">{e.ip ?? "—"}</td>
              <td className="max-w-64 truncate text-xs text-ink-3" title={e.user_agent ?? undefined}>
                {e.user_agent ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      <Pagination page={page} size={50} total={events.data.total} onChange={setPage} />
    </>
  );
}
