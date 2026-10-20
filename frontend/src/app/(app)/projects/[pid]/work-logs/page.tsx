"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, startOfMonth } from "date-fns";
import { Clock, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

import { EnumSelect, MemberSelect } from "@/components/project/selects";
import { WorkLogModal } from "@/components/project/work-log-form";
import { Badge } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/form";
import { Card, CardHeader, Empty, Pagination, ProgressBar, Spinner, Table, UserChip } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, clean } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMembers, useProjectId, useProjectPerms } from "@/lib/hooks";
import { ACTIVITY_TYPE } from "@/lib/labels";
import type { ActivityType, Page, WorkItem, WorkLog, WorkLogSummaryRow } from "@/lib/types";
import { fmtDate, fmtHours, num, todayISO } from "@/lib/utils";

const GROUPS = { user: "Theo người", date: "Theo ngày", activity_type: "Theo loại việc", sprint: "Theo sprint", work_item: "Theo công việc" };
type Group = keyof typeof GROUPS;

export default function WorkLogsPage() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const toast = useToast();
  const { me } = useAuth();
  const { can } = useProjectPerms(pid);
  const { byId } = useMembers(pid);
  const [page, setPage] = useState(1);
  const [logOpen, setLogOpen] = useState(false);
  const [editing, setEditing] = useState<WorkLog | null>(null);
  const [group, setGroup] = useState<Group>("user");
  const [filters, setFilters] = useState({
    user_id: null as number | null,
    date_from: format(startOfMonth(new Date()), "yyyy-MM-dd"),
    date_to: todayISO(),
    activity_type: "" as ActivityType | "",
  });
  const setFilter = <K extends keyof typeof filters>(k: K, v: (typeof filters)[K]) => {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(1);
  };

  const params = clean({ ...filters, user_id: filters.user_id ?? undefined, page, size: 30 });
  const logs = useQuery({
    queryKey: ["project", pid, "work-logs", params],
    queryFn: async () => (await api.get<Page<WorkLog>>(`/projects/${pid}/work-logs`, { params })).data,
    placeholderData: keepPreviousData,
  });
  const summary = useQuery({
    queryKey: ["project", pid, "work-logs", "summary", group, filters.date_from, filters.date_to],
    queryFn: async () =>
      (
        await api.get<WorkLogSummaryRow[]>(`/projects/${pid}/reports/work-logs`, {
          params: clean({ group_by: group, date_from: filters.date_from, date_to: filters.date_to }),
        })
      ).data,
    enabled: can("report.view"),
  });
  const workItems = useQuery({
    queryKey: ["project", pid, "work-items", "all"],
    queryFn: async () =>
      (await api.get<Page<WorkItem>>(`/projects/${pid}/work-items`, { params: { size: 500 } })).data.items,
  });
  const itemCode = new Map(workItems.data?.map((w) => [w.id, w]));

  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/projects/${pid}/work-logs/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", pid] });
      toast.success("Đã xoá log");
    },
    onError: toast.error,
  });

  const canManage = can("work_log.manage");
  const total = (summary.data ?? []).reduce((s, r) => s + num(r.total_hours), 0);
  const maxRow = Math.max(1, ...(summary.data ?? []).map((r) => num(r.total_hours)));
  const groupLabel = (r: WorkLogSummaryRow) => {
    if (r.key === "none") return group === "sprint" ? "Ngoài sprint" : "Không gắn công việc";
    if (group === "activity_type") return ACTIVITY_TYPE[r.key as ActivityType] ?? r.key;
    if (group === "date") return fmtDate(r.key);
    return r.label ?? r.key;
  };

  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <Card className="xl:col-span-2">
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <MemberSelect
            aria-label="Thành viên"
            className="w-44"
            pid={pid}
            value={filters.user_id}
            onChange={(v) => setFilter("user_id", v)}
            emptyLabel="Mọi thành viên"
          />
          <Input
            aria-label="Từ ngày"
            type="date"
            className="w-38"
            value={filters.date_from}
            onChange={(e) => setFilter("date_from", e.target.value)}
          />
          <span className="text-ink-3">→</span>
          <Input
            aria-label="Đến ngày"
            type="date"
            className="w-38"
            value={filters.date_to}
            onChange={(e) => setFilter("date_to", e.target.value)}
          />
          <EnumSelect
            aria-label="Loại việc"
            className="w-36"
            options={ACTIVITY_TYPE}
            value={filters.activity_type}
            onChange={(v) => setFilter("activity_type", v)}
            emptyLabel="Mọi loại việc"
          />
          {can("work_log.create") && (
            <Button
              variant="primary"
              className="ml-auto"
              icon={<Clock className="size-4" />}
              onClick={() => setLogOpen(true)}
            >
              Ghi log
            </Button>
          )}
        </div>

        {logs.isPending ? (
          <Spinner />
        ) : !logs.data?.items.length ? (
          <Empty title="Không có log trong khoảng thời gian này" />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Ngày</th>
                <th>Thành viên</th>
                <th className="text-right">Giờ</th>
                <th>Nội dung</th>
                <th>Loại</th>
                <th className="w-20" />
              </tr>
            </thead>
            <tbody>
              {logs.data.items.map((l) => {
                const item = l.work_item_id ? itemCode.get(l.work_item_id) : undefined;
                const editable = l.user_id === me?.id || canManage;
                return (
                  <tr key={l.id}>
                    <td className="whitespace-nowrap tabular-nums">{fmtDate(l.log_date)}</td>
                    <td className="whitespace-nowrap">
                      <UserChip id={l.user_id} name={byId.get(l.user_id)?.full_name ?? `#${l.user_id}`} />
                    </td>
                    <td className="text-right font-semibold tabular-nums">{fmtHours(l.hours)}</td>
                    <td className="max-w-sm">
                      <p className="truncate">{l.description}</p>
                      {item && (
                        <p className="truncate text-xs text-ink-3">
                          <span className="font-mono">{item.code}</span> · {item.title}
                        </p>
                      )}
                    </td>
                    <td className="whitespace-nowrap">
                      {ACTIVITY_TYPE[l.activity_type]}
                      {!l.is_billable && (
                        <Badge className="ml-1.5" tone="gray">
                          Không tính phí
                        </Badge>
                      )}
                    </td>
                    <td className="text-right whitespace-nowrap">
                      {editable && (
                        <>
                          <IconButton label="Sửa log" onClick={() => setEditing(l)}>
                            <Pencil className="size-3.5" />
                          </IconButton>
                          <IconButton
                            label="Xoá log"
                            className="hover:bg-danger-soft hover:text-danger"
                            onClick={() => confirm("Xoá log này?") && remove.mutate(l.id)}
                          >
                            <Trash2 className="size-3.5" />
                          </IconButton>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
        {logs.data && <Pagination page={page} size={logs.data.size} total={logs.data.total} onChange={setPage} />}
      </Card>

      {can("report.view") && (
        <Card className="self-start">
          <CardHeader
            title={`Tổng hợp · ${fmtHours(total)}`}
            action={
              <Select
                aria-label="Nhóm theo"
                className="h-8 w-36 text-[13px]"
                value={group}
                onChange={(e) => setGroup(e.target.value as Group)}
              >
                {Object.entries(GROUPS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </Select>
            }
          />
          {summary.isPending ? (
            <Spinner />
          ) : !summary.data?.length ? (
            <p className="px-4 py-6 text-sm text-ink-3">Chưa có dữ liệu.</p>
          ) : (
            <ul className="max-h-[520px] space-y-3 overflow-y-auto px-4 py-4">
              {summary.data.map((r) => (
                <li key={r.key} className="text-sm">
                  <div className="mb-1 flex justify-between gap-2">
                    <span className="truncate text-ink-2">{groupLabel(r)}</span>
                    <span className="shrink-0 tabular-nums">
                      <span className="font-semibold">{fmtHours(r.total_hours)}</span>
                      {num(r.billable_hours) !== num(r.total_hours) && (
                        <span className="ml-1 text-xs text-ink-3">({fmtHours(r.billable_hours)} tính phí)</span>
                      )}
                    </span>
                  </div>
                  <ProgressBar value={(num(r.total_hours) / maxRow) * 100} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {logOpen && <WorkLogModal open pid={pid} onClose={() => setLogOpen(false)} />}
      {editing && <WorkLogModal open pid={pid} log={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}
