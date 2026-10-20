"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";

import { RequirementFormModal } from "@/components/project/requirement-form";
import { EnumSelect, MemberSelect } from "@/components/project/selects";
import { Badge, MetaBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox, Input, Select } from "@/components/ui/form";
import { Card, Empty, Pagination, Spinner, Table, UserChip } from "@/components/ui/misc";
import { api, clean } from "@/lib/api";
import { useMembers, useProjectId, useProjectPerms } from "@/lib/hooks";
import { PRIORITY, REQUIREMENT_STATUS, REQUIREMENT_TYPE } from "@/lib/labels";
import type { Page, Priority, Requirement, RequirementStatus, RequirementType } from "@/lib/types";
import { cn, daysUntil, fmtDate } from "@/lib/utils";

const SORTS = {
  "-received_at": "Mới tiếp nhận",
  due_date: "Hạn gần nhất",
  "-priority": "Ưu tiên cao",
  "-business_value": "Giá trị cao",
  code: "Mã tăng dần",
};
const OPEN_STATUSES: RequirementStatus[] = ["new", "analyzing", "pending_approval", "approved", "in_progress"];

export default function RequirementsPage() {
  const pid = useProjectId();
  const { can } = useProjectPerms(pid);
  const { byId } = useMembers(pid);
  const [creating, setCreating] = useState(false);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    q: "",
    status: "open" as RequirementStatus | "open" | "",
    priority: "" as Priority | "",
    type: "" as RequirementType | "",
    assignee_id: null as number | null,
    overdue: false,
    sort: "-received_at",
  });
  const q = useDeferredValue(filters.q);
  const setFilter = <K extends keyof typeof filters>(k: K, v: (typeof filters)[K]) => {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(1);
  };

  const params = clean({
    q,
    status: filters.status === "open" ? OPEN_STATUSES : filters.status,
    priority: filters.priority,
    type: filters.type,
    assignee_id: filters.assignee_id ?? undefined,
    overdue: filters.overdue || undefined,
    sort: filters.sort,
    page,
    size: 25,
  });
  const query = useQuery({
    queryKey: ["project", pid, "requirements", params],
    queryFn: async () => (await api.get<Page<Requirement>>(`/projects/${pid}/requirements`, { params })).data,
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-3" />
            <Input
              aria-label="Tìm yêu cầu"
              placeholder="Tìm mã, tiêu đề, mô tả…"
              className="pl-8"
              value={filters.q}
              onChange={(e) => setFilter("q", e.target.value)}
            />
          </div>
          <Select
            aria-label="Trạng thái"
            className="w-40"
            value={filters.status}
            onChange={(e) => setFilter("status", e.target.value as typeof filters.status)}
          >
            <option value="open">Đang mở</option>
            <option value="">Tất cả trạng thái</option>
            {Object.entries(REQUIREMENT_STATUS).map(([k, m]) => (
              <option key={k} value={k}>
                {m.label}
              </option>
            ))}
          </Select>
          <EnumSelect
            aria-label="Ưu tiên"
            className="w-36"
            options={PRIORITY}
            value={filters.priority}
            onChange={(v) => setFilter("priority", v)}
            emptyLabel="Mọi ưu tiên"
          />
          <EnumSelect
            aria-label="Loại"
            className="w-36"
            options={REQUIREMENT_TYPE}
            value={filters.type}
            onChange={(v) => setFilter("type", v)}
            emptyLabel="Mọi loại"
          />
          <MemberSelect
            aria-label="Người phụ trách"
            className="w-44"
            pid={pid}
            value={filters.assignee_id}
            onChange={(v) => setFilter("assignee_id", v)}
            emptyLabel="Mọi người phụ trách"
          />
          <Checkbox label="Quá hạn" checked={filters.overdue} onChange={(e) => setFilter("overdue", e.target.checked)} />
          <div className="ml-auto flex items-center gap-2">
            <Select
              aria-label="Sắp xếp"
              className="w-40"
              value={filters.sort}
              onChange={(e) => setFilter("sort", e.target.value)}
            >
              {Object.entries(SORTS).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </Select>
            {can("requirement.create") && (
              <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
                Thêm yêu cầu
              </Button>
            )}
          </div>
        </div>

        {query.isPending ? (
          <Spinner />
        ) : !query.data?.items.length ? (
          <Empty
            title="Không có yêu cầu phù hợp"
            description="Thử bỏ bớt bộ lọc, hoặc tạo yêu cầu mới từ khách hàng."
          />
        ) : (
          <Table className={cn(query.isFetching && "opacity-70")}>
            <thead>
              <tr>
                <th className="w-32">Mã</th>
                <th>Tiêu đề</th>
                <th>Loại</th>
                <th>Ưu tiên</th>
                <th>Trạng thái</th>
                <th>Phụ trách</th>
                <th>Hạn</th>
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((r) => {
                const left = daysUntil(r.due_date);
                const closed = ["done", "closed", "cancelled", "rejected"].includes(r.status);
                return (
                  <tr key={r.id}>
                    <td className="font-mono text-xs text-ink-2">{r.code}</td>
                    <td className="max-w-md">
                      <Link
                        href={`/projects/${pid}/requirements/${r.id}`}
                        className="font-medium hover:text-brand hover:underline"
                      >
                        {r.title}
                      </Link>
                      {r.tags.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {r.tags.map((t) => (
                            <span key={t} className="rounded bg-subtle px-1.5 py-0.5 text-[11px] text-ink-2">
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="text-ink-2">{REQUIREMENT_TYPE[r.type]}</td>
                    <td>
                      <MetaBadge meta={PRIORITY[r.priority]} />
                    </td>
                    <td>
                      <MetaBadge meta={REQUIREMENT_STATUS[r.status]} />
                    </td>
                    <td>
                      <UserChip id={r.assignee_id} name={r.assignee_id ? byId.get(r.assignee_id)?.full_name : null} />
                    </td>
                    <td className="whitespace-nowrap tabular-nums">
                      {fmtDate(r.due_date)}
                      {left !== null && left < 0 && !closed && (
                        <Badge tone="red" className="ml-1.5">
                          Trễ {-left}d
                        </Badge>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
        {query.data && <Pagination page={page} size={query.data.size} total={query.data.total} onChange={setPage} />}
      </Card>

      {creating && <RequirementFormModal open pid={pid} onClose={() => setCreating(false)} />}
    </>
  );
}
