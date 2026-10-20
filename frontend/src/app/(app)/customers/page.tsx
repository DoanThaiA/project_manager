"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, Pencil, Phone, Plus, Search, Star, Trash2 } from "lucide-react";
import { useDeferredValue, useState } from "react";

import { MetaBadge } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/form";
import { Card, CardHeader, Empty, PageHeader, Pagination, Spinner, Table } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api, clean } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Contact, Customer, Page } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS = { active: { label: "Hoạt động", tone: "green" as const }, inactive: { label: "Ngừng", tone: "gray" as const } };

function CustomerModal({ customer, onClose }: { customer?: Customer; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const editing = !!customer;
  const [form, setForm] = useState({
    code: customer?.code ?? "",
    name: customer?.name ?? "",
    tax_code: customer?.tax_code ?? "",
    email: customer?.email ?? "",
    phone: customer?.phone ?? "",
    address: customer?.address ?? "",
    website: customer?.website ?? "",
    note: customer?.note ?? "",
    status: customer?.status ?? "active",
  });
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const save = useMutation({
    mutationFn: async () => {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === "" ? null : v]));
      return editing
        ? api.patch(`/customers/${customer.id}`, { ...body, code: undefined })
        : api.post("/customers", { ...body, status: undefined });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["customers"] });
      toast.success(editing ? "Đã lưu khách hàng" : "Đã thêm khách hàng");
      onClose();
    },
    onError: toast.error,
  });

  const text = (key: keyof typeof form, label: string, opts: { required?: boolean; type?: string; span?: boolean } = {}) => (
    <Field label={label} required={opts.required} className={cn(opts.span && "sm:col-span-2")}>
      {(id) => (
        <Input
          id={id}
          type={opts.type ?? "text"}
          value={form[key]}
          disabled={editing && key === "code"}
          onChange={(e) => set(key, e.target.value)}
        />
      )}
    </Field>
  );

  return (
    <Modal
      open
      onClose={onClose}
      title={editing ? `Sửa ${customer.name}` : "Khách hàng mới"}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button
            variant="primary"
            loading={save.isPending}
            disabled={!form.code.trim() || !form.name.trim()}
            onClick={() => save.mutate()}
          >
            Lưu
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {text("code", "Mã khách hàng", { required: true })}
        {text("tax_code", "Mã số thuế")}
        {text("name", "Tên khách hàng", { required: true, span: true })}
        {text("email", "Email", { type: "email" })}
        {text("phone", "Điện thoại")}
        {text("address", "Địa chỉ", { span: true })}
        {text("website", "Website")}
        {editing && (
          <Field label="Trạng thái">
            {(id) => (
              <Select id={id} value={form.status} onChange={(e) => set("status", e.target.value)}>
                <option value="active">Hoạt động</option>
                <option value="inactive">Ngừng</option>
              </Select>
            )}
          </Field>
        )}
        <Field label="Ghi chú" className="sm:col-span-2">
          {(id) => <Textarea id={id} value={form.note} onChange={(e) => set("note", e.target.value)} />}
        </Field>
      </div>
    </Modal>
  );
}

function Contacts({ customer }: { customer: Customer }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useAuth();
  const key = ["customers", customer.id, "contacts"];
  const [form, setForm] = useState({ full_name: "", position: "", email: "", phone: "", is_primary: false });
  const contacts = useQuery({
    queryKey: key,
    queryFn: async () => (await api.get<Contact[]>(`/customers/${customer.id}/contacts`)).data,
  });
  const add = useMutation({
    mutationFn: () => api.post(`/customers/${customer.id}/contacts`, clean(form)),
    onSuccess: () => {
      setForm({ full_name: "", position: "", email: "", phone: "", is_primary: false });
      qc.invalidateQueries({ queryKey: key });
    },
    onError: toast.error,
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<Contact> }) =>
      api.patch(`/customers/${customer.id}/contacts/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
    onError: toast.error,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/customers/${customer.id}/contacts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
    onError: toast.error,
  });
  const canEdit = can("customer.update");

  return (
    <div className="space-y-4">
      {contacts.isPending ? (
        <Spinner />
      ) : !contacts.data?.length ? (
        <p className="text-sm text-ink-3">Chưa có người liên hệ.</p>
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {contacts.data.map((c) => (
            <li key={c.id} className="flex items-center gap-3 px-3 py-2.5 text-sm">
              <div className="min-w-0 flex-1">
                <p className="font-medium">
                  {c.full_name}
                  {c.position && <span className="font-normal text-ink-3"> · {c.position}</span>}
                </p>
                <p className="flex flex-wrap gap-x-3 text-xs text-ink-3">
                  {c.email && (
                    <a href={`mailto:${c.email}`} className="inline-flex items-center gap-1 hover:text-brand">
                      <Mail className="size-3" /> {c.email}
                    </a>
                  )}
                  {c.phone && (
                    <span className="inline-flex items-center gap-1">
                      <Phone className="size-3" /> {c.phone}
                    </span>
                  )}
                </p>
              </div>
              {canEdit ? (
                <>
                  <IconButton
                    label={c.is_primary ? "Đầu mối chính" : "Đặt làm đầu mối chính"}
                    className={cn(c.is_primary && "text-amber-500")}
                    onClick={() => !c.is_primary && update.mutate({ id: c.id, body: { is_primary: true } })}
                  >
                    <Star className={cn("size-4", c.is_primary && "fill-current")} />
                  </IconButton>
                  <IconButton
                    label="Xoá người liên hệ"
                    className="hover:bg-danger-soft hover:text-danger"
                    onClick={() => confirm(`Xoá ${c.full_name}?`) && remove.mutate(c.id)}
                  >
                    <Trash2 className="size-4" />
                  </IconButton>
                </>
              ) : (
                c.is_primary && <Star className="size-4 fill-current text-amber-500" aria-label="Đầu mối chính" />
              )}
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <form
          className="grid gap-2 rounded-lg bg-subtle p-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (form.full_name.trim()) add.mutate();
          }}
        >
          <Input
            aria-label="Họ tên"
            placeholder="Họ tên *"
            value={form.full_name}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
          />
          <Input
            aria-label="Chức vụ"
            placeholder="Chức vụ"
            value={form.position}
            onChange={(e) => setForm({ ...form, position: e.target.value })}
          />
          <Input
            aria-label="Email"
            type="email"
            placeholder="Email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
          <Input
            aria-label="Điện thoại"
            placeholder="Điện thoại"
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
          />
          <Checkbox
            label="Đầu mối chính"
            checked={form.is_primary}
            onChange={(e) => setForm({ ...form, is_primary: e.target.checked })}
          />
          <Button type="submit" size="sm" className="justify-self-end" loading={add.isPending} disabled={!form.full_name.trim()}>
            Thêm người liên hệ
          </Button>
        </form>
      )}
    </div>
  );
}

export default function CustomersPage() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState<{ customer?: Customer } | null>(null);
  const [selected, setSelected] = useState<Customer | null>(null);
  const params = clean({ q: useDeferredValue(q), page, size: 20 });
  const customers = useQuery({
    queryKey: ["customers", params],
    queryFn: async () => (await api.get<Page<Customer>>("/customers", { params })).data,
    placeholderData: keepPreviousData,
  });
  const current = customers.data?.items.find((c) => c.id === selected?.id) ?? selected;

  return (
    <>
      <PageHeader
        title="Khách hàng"
        actions={
          can("customer.create") && (
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setModal({})}>
              Khách hàng mới
            </Button>
          )
        }
      />
      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <div className="border-b border-line p-3">
            <div className="relative sm:w-72">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-3" />
              <Input
                aria-label="Tìm khách hàng"
                placeholder="Tìm mã, tên, email…"
                className="pl-8"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setPage(1);
                }}
              />
            </div>
          </div>
          {customers.isPending ? (
            <Spinner />
          ) : !customers.data?.items.length ? (
            <Empty title="Chưa có khách hàng" />
          ) : (
            <Table>
              <thead>
                <tr>
                  <th>Mã</th>
                  <th>Tên</th>
                  <th>Liên hệ</th>
                  <th>Trạng thái</th>
                </tr>
              </thead>
              <tbody>
                {customers.data.items.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => setSelected(c)}
                    className={cn("cursor-pointer", current?.id === c.id && "!bg-brand-soft/60")}
                  >
                    <td className="font-mono text-xs">{c.code}</td>
                    <td className="font-medium">{c.name}</td>
                    <td className="text-xs text-ink-3">
                      {c.email}
                      {c.phone && <span className="block">{c.phone}</span>}
                    </td>
                    <td>
                      <MetaBadge meta={STATUS[c.status]} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          {customers.data && (
            <Pagination page={page} size={customers.data.size} total={customers.data.total} onChange={setPage} />
          )}
        </Card>

        <Card className="self-start lg:col-span-2">
          {current ? (
            <>
              <CardHeader
                title={current.name}
                action={
                  can("customer.update") && (
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Pencil className="size-3.5" />}
                      onClick={() => setModal({ customer: current })}
                    >
                      Sửa
                    </Button>
                  )
                }
              />
              <div className="space-y-4 p-4">
                <dl className="grid grid-cols-[100px_1fr] gap-x-3 gap-y-2 text-sm">
                  <dt className="text-ink-3">Mã số thuế</dt>
                  <dd>{current.tax_code ?? "—"}</dd>
                  <dt className="text-ink-3">Địa chỉ</dt>
                  <dd>{current.address ?? "—"}</dd>
                  <dt className="text-ink-3">Website</dt>
                  <dd className="truncate">{current.website ?? "—"}</dd>
                  {current.note && (
                    <>
                      <dt className="text-ink-3">Ghi chú</dt>
                      <dd className="whitespace-pre-line">{current.note}</dd>
                    </>
                  )}
                </dl>
                <div>
                  <h4 className="mb-2 text-[13px] font-semibold text-ink-2">Người liên hệ</h4>
                  <Contacts customer={current} />
                </div>
              </div>
            </>
          ) : (
            <Empty title="Chọn một khách hàng" description="Xem thông tin chi tiết và người liên hệ." />
          )}
        </Card>
      </div>
      {modal && <CustomerModal customer={modal.customer} onClose={() => setModal(null)} />}
    </>
  );
}
