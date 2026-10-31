"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";

import { CrmContactFormModal, CrmContactModal, contactName, crmKey } from "@/components/project/crm";
import { EnumSelect } from "@/components/project/selects";
import { MetaBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/form";
import { Card, Empty, Pagination, Spinner, Stat, Table, UserChip } from "@/components/ui/misc";
import { api, clean } from "@/lib/api";
import { useMembers, useProjectId, useProjectPerms } from "@/lib/hooks";
import { CRM_CLOSED_STATUSES, CRM_INQUIRY_TYPE, CRM_STATUS } from "@/lib/labels";
import type { CrmContact, CrmContactStatus, CrmEmail, CrmInquiryType, CrmStats, Page } from "@/lib/types";
import { cn, fmtDateTime, fmtRelative } from "@/lib/utils";

const SORTS = {
  "-last_contact_at": "Liên hệ gần nhất",
  "-created_at": "Mới thêm",
  "-email_count": "Nhiều email nhất",
  full_name: "Tên A–Z",
};
const OPEN_STATUSES = (Object.keys(CRM_STATUS) as CrmContactStatus[]).filter((s) => !CRM_CLOSED_STATUSES.includes(s));

function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <div className="relative w-full sm:w-64">
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-3" />
      <Input
        aria-label={placeholder}
        placeholder={placeholder}
        className="pl-8"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export default function CrmPage() {
  const pid = useProjectId();
  const { can } = useProjectPerms(pid);
  const [view, setView] = useState<"contacts" | "emails">("contacts");
  const [openId, setOpenId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);

  const stats = useQuery({
    queryKey: [...crmKey(pid), "stats"],
    queryFn: async () => (await api.get<CrmStats>(`/projects/${pid}/crm/stats`)).data,
  });
  const s = stats.data;

  return (
    <>
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Khách liên hệ" value={s?.total ?? "—"} sub={s && `${s.by_status.new} khách mới`} />
        <Stat label="Email 7 ngày qua" value={s?.emails_7d ?? "—"} />
        <Stat
          label="Đang mở, chưa phụ trách"
          value={s?.unassigned ?? "—"}
          className={cn(s && s.unassigned > 0 && "ring-1 ring-amber-200")}
        />
        <Stat
          label="Chốt đơn"
          value={s?.by_status.won ?? "—"}
          sub={s && `${s.by_status.quoted + s.by_status.negotiating} đang báo giá / thương lượng`}
        />
      </div>

      <Card>
        <div className="flex items-center gap-1 border-b border-line px-3 pt-2" role="tablist">
          {(
            [
              ["contacts", "Khách liên hệ"],
              ["emails", "Email nhận được"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={view === key}
              onClick={() => setView(key)}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-[13px] font-medium whitespace-nowrap transition-colors",
                view === key ? "border-brand text-brand" : "border-transparent text-ink-3 hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
          {can("crm.create") && (
            <Button
              size="sm"
              variant="primary"
              className="mb-1.5 ml-auto"
              icon={<Plus className="size-4" />}
              onClick={() => setCreating(true)}
            >
              Thêm khách
            </Button>
          )}
        </div>
        {view === "contacts" ? (
          <ContactsView pid={pid} stats={s} onOpen={setOpenId} />
        ) : (
          <EmailsView pid={pid} onOpen={setOpenId} />
        )}
      </Card>

      {openId !== null && <CrmContactModal pid={pid} contactId={openId} onClose={() => setOpenId(null)} />}
      {creating && <CrmContactFormModal pid={pid} onClose={() => setCreating(false)} onSaved={(c) => setOpenId(c.id)} />}
    </>
  );
}

function ContactsView({ pid, stats, onOpen }: { pid: number; stats?: CrmStats; onOpen: (id: number) => void }) {
  const { members, byId } = useMembers(pid);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    q: "",
    status: "open" as CrmContactStatus | "open" | "",
    inquiry_type: "" as CrmInquiryType | "",
    assignee_id: "" as string, // "" = mọi người, "0" = chưa phụ trách
    sort: "-last_contact_at",
  });
  const q = useDeferredValue(filters.q);
  const setFilter = <K extends keyof typeof filters>(k: K, v: (typeof filters)[K]) => {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(1);
  };

  const params = clean({
    q,
    status: filters.status === "open" ? OPEN_STATUSES : filters.status,
    inquiry_type: filters.inquiry_type,
    assignee_id: filters.assignee_id,
    sort: filters.sort,
    page,
    size: 25,
  });
  const query = useQuery({
    queryKey: [...crmKey(pid), "contacts", params],
    queryFn: async () => (await api.get<Page<CrmContact>>(`/projects/${pid}/crm/contacts`, { params })).data,
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <SearchBox value={filters.q} onChange={(v) => setFilter("q", v)} placeholder="Tìm tên, email, công ty, SĐT…" />
        <Select
          aria-label="Trạng thái"
          className="w-48"
          value={filters.status}
          onChange={(e) => setFilter("status", e.target.value as typeof filters.status)}
        >
          <option value="open">Đang theo dõi</option>
          <option value="">Tất cả trạng thái</option>
          {Object.entries(CRM_STATUS).map(([k, m]) => (
            <option key={k} value={k}>
              {m.label}
              {stats ? ` (${stats.by_status[k as CrmContactStatus]})` : ""}
            </option>
          ))}
        </Select>
        <EnumSelect
          aria-label="Nhu cầu"
          className="w-40"
          options={CRM_INQUIRY_TYPE}
          value={filters.inquiry_type}
          onChange={(v) => setFilter("inquiry_type", v)}
          emptyLabel="Mọi nhu cầu"
        />
        <Select
          aria-label="Người phụ trách"
          className="w-44"
          value={filters.assignee_id}
          onChange={(e) => setFilter("assignee_id", e.target.value)}
        >
          <option value="">Mọi người phụ trách</option>
          <option value="0">Chưa phụ trách</option>
          {members.map((m) => (
            <option key={m.user.id} value={m.user.id}>
              {m.user.full_name}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Sắp xếp"
          className="ml-auto w-44"
          value={filters.sort}
          onChange={(e) => setFilter("sort", e.target.value)}
        >
          {Object.entries(SORTS).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </Select>
      </div>

      {query.isPending ? (
        <Spinner />
      ) : !query.data?.items.length ? (
        <Empty
          title="Chưa có khách liên hệ phù hợp"
          description="Khách sẽ tự xuất hiện khi n8n gửi email từ Gmail về, hoặc bấm “Thêm khách” để nhập tay."
        />
      ) : (
        <Table className={cn(query.isFetching && "opacity-70")}>
          <thead>
            <tr>
              <th>Khách</th>
              <th>Công ty · SĐT</th>
              <th>Nhu cầu</th>
              <th className="text-right">Email</th>
              <th>Liên hệ cuối</th>
              <th>Trạng thái</th>
              <th>Phụ trách</th>
            </tr>
          </thead>
          <tbody>
            {query.data.items.map((c) => (
              <tr key={c.id} className="cursor-pointer" onClick={() => onOpen(c.id)}>
                <td className="max-w-64">
                  <button
                    type="button"
                    className="block max-w-full truncate text-left font-medium hover:text-brand hover:underline"
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpen(c.id);
                    }}
                  >
                    {contactName(c)}
                  </button>
                  {c.full_name && <span className="block truncate text-xs text-ink-3">{c.email}</span>}
                </td>
                <td className="max-w-56 text-ink-2">
                  <span className="block truncate">{c.company ?? "—"}</span>
                  {c.phone && <span className="block truncate text-xs text-ink-3">{c.phone}</span>}
                </td>
                <td>
                  {c.last_inquiry_type ? (
                    <MetaBadge meta={CRM_INQUIRY_TYPE[c.last_inquiry_type]} dot={false} />
                  ) : (
                    <span className="text-ink-3">—</span>
                  )}
                </td>
                <td className="text-right tabular-nums">{c.email_count}</td>
                <td className="whitespace-nowrap text-ink-2" title={fmtDateTime(c.last_contact_at ?? c.created_at)}>
                  {fmtRelative(c.last_contact_at ?? c.created_at)}
                </td>
                <td>
                  <MetaBadge meta={CRM_STATUS[c.status]} />
                </td>
                <td>
                  <UserChip id={c.assignee_id} name={c.assignee_id ? byId.get(c.assignee_id)?.full_name : null} />
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {query.data && <Pagination page={page} size={query.data.size} total={query.data.total} onChange={setPage} />}
    </>
  );
}

function EmailsView({ pid, onOpen }: { pid: number; onOpen: (contactId: number) => void }) {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({
    q: "",
    inquiry_type: "" as CrmInquiryType | "",
    date_from: "",
    date_to: "",
  });
  const q = useDeferredValue(filters.q);
  const setFilter = <K extends keyof typeof filters>(k: K, v: (typeof filters)[K]) => {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(1);
  };

  const params = clean({ ...filters, q, page, size: 25 });
  const query = useQuery({
    queryKey: [...crmKey(pid), "emails", params],
    queryFn: async () => (await api.get<Page<CrmEmail>>(`/projects/${pid}/crm/emails`, { params })).data,
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <SearchBox value={filters.q} onChange={(v) => setFilter("q", v)} placeholder="Tìm tiêu đề, người gửi, tóm tắt…" />
        <EnumSelect
          aria-label="Nhu cầu"
          className="w-40"
          options={CRM_INQUIRY_TYPE}
          value={filters.inquiry_type}
          onChange={(v) => setFilter("inquiry_type", v)}
          emptyLabel="Mọi nhu cầu"
        />
        <label className="flex items-center gap-1.5 text-[13px] text-ink-3">
          Từ
          <Input
            type="date"
            className="w-36"
            value={filters.date_from}
            onChange={(e) => setFilter("date_from", e.target.value)}
          />
        </label>
        <label className="flex items-center gap-1.5 text-[13px] text-ink-3">
          đến
          <Input
            type="date"
            className="w-36"
            value={filters.date_to}
            onChange={(e) => setFilter("date_to", e.target.value)}
          />
        </label>
      </div>

      {query.isPending ? (
        <Spinner />
      ) : !query.data?.items.length ? (
        <Empty title="Chưa có email phù hợp" description="Email khách liên hệ do n8n lọc từ Gmail sẽ hiện ở đây." />
      ) : (
        <Table className={cn(query.isFetching && "opacity-70")}>
          <thead>
            <tr>
              <th className="w-36">Nhận lúc</th>
              <th>Người gửi</th>
              <th>Tiêu đề / tóm tắt</th>
              <th>Nhu cầu</th>
              <th>Sản phẩm · SL</th>
            </tr>
          </thead>
          <tbody>
            {query.data.items.map((e) => (
              <tr key={e.id} className="cursor-pointer" onClick={() => onOpen(e.contact_id)}>
                <td className="whitespace-nowrap text-ink-2 tabular-nums">{fmtDateTime(e.received_at)}</td>
                <td className="max-w-52">
                  <span className="block truncate font-medium">{e.customer_name || e.customer_email}</span>
                  {e.customer_name && <span className="block truncate text-xs text-ink-3">{e.customer_email}</span>}
                </td>
                <td className="max-w-md">
                  <span className="block truncate">{e.subject || "(Không có tiêu đề)"}</span>
                  {e.summary && <span className="line-clamp-2 text-xs text-ink-3">{e.summary}</span>}
                </td>
                <td>
                  <MetaBadge meta={CRM_INQUIRY_TYPE[e.inquiry_type]} dot={false} />
                </td>
                <td className="max-w-48 text-ink-2">
                  <span className="line-clamp-2">
                    {[e.product_type, e.quantity].filter(Boolean).join(" · ") || "—"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {query.data && <Pagination page={page} size={query.data.size} total={query.data.total} onChange={setPage} />}
    </>
  );
}
