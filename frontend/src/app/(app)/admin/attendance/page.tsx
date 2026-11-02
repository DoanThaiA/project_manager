"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { endOfMonth, format, parseISO } from "date-fns";
import { vi } from "date-fns/locale";
import { Download, Pencil, Plus, Trash2, Wifi } from "lucide-react";
import { useState } from "react";

import { RecordBadges, fmtMinutes, fmtTime } from "@/components/attendance";
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
  AttendanceSummary,
  MyIp,
  Page,
  UserBrief,
} from "@/lib/types";
import { cn, fmtDateTime } from "@/lib/utils";

type Tab = "records" | "summary" | "networks" | "events";

const FLAGS = { late: "Đi muộn", early_leave: "Về sớm", missing_checkout: "Thiếu check-out" } as const;
const REASONS: Record<string, string> = {
  outside_network: "Ngoài mạng công ty",
  not_checked_in: "Check-out khi chưa check-in",
  api_token: "Dùng token PAT",
};

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
  const users = summary.data?.rows.map((r) => r.user) ?? [];

  const tabs: [Tab, string][] = [
    ["records", "Bảng công"],
    ["summary", "Tổng hợp tháng"],
    ...(manage
      ? ([
          ["networks", "Mạng công ty"],
          ["events", "Lần bị từ chối"],
        ] as [Tab, string][])
      : []),
  ];

  return (
    <>
      <PageHeader
        title="Chấm công"
        description="Ca cố định, chấm công theo IP mạng công ty"
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
        {tab === "records" && <RecordsTab month={month} users={users} manage={manage} />}
        {tab === "summary" && <SummaryTab month={month} data={summary.data} loading={summary.isPending} />}
        {tab === "networks" && manage && <NetworksTab />}
        {tab === "events" && manage && <EventsTab />}
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- Bảng công

function RecordsTab({ month, users, manage }: { month: string; users: UserBrief[]; manage: boolean }) {
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
                <th>Vào</th>
                <th>Về</th>
                <th>Giờ làm</th>
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
                  <td className="tabular-nums">{fmtTime(r.check_in_at)}</td>
                  <td className="tabular-nums">{fmtTime(r.check_out_at)}</td>
                  <td className="tabular-nums">{fmtMinutes(r.worked_minutes)}</td>
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
        <RecordModal record={editing === "new" ? undefined : editing} users={users} onClose={() => setEditing(null)} />
      )}
    </>
  );
}

function RecordModal({
  record,
  users,
  onClose,
}: {
  record?: AttendanceRecord;
  users: UserBrief[];
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
    note: record?.note ?? "",
    adjusted_reason: "",
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));

  const save = useMutation({
    mutationFn: async () => {
      const times = {
        check_in_time: form.check_in_time,
        check_out_time: form.check_out_time || null,
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
        <span>
          {data?.work_days ?? 0} ngày làm việc đã qua trong tháng · {data?.rows.length ?? 0} nhân viên
        </span>
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
              <th className="text-right">Có mặt</th>
              <th className="text-right">Vắng</th>
              <th className="text-right">Đi muộn</th>
              <th className="text-right">Về sớm</th>
              <th className="text-right">Thiếu check-out</th>
              <th className="text-right">Giờ làm</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.user.id}>
                <td>
                  <UserChip id={r.user.id} name={r.user.full_name} />
                </td>
                <td className="text-right tabular-nums">{r.present_days}</td>
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
                <td className="text-right font-medium tabular-nums">{fmtMinutes(r.worked_minutes)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </>
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
