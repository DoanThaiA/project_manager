"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Mail, Pencil, Phone, Plus, ScanLine, Search, Star, Trash2, UserPlus } from "lucide-react";
import { useDeferredValue, useEffect, useRef, useState } from "react";

import { MetaBadge } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/form";
import { Card, CardHeader, Empty, PageHeader, Pagination, Spinner, Table } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api, clean } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Contact, ContactOcr, Customer, Page } from "@/lib/types";
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

const CARD_MAX_BYTES = 1024 * 1024; // OCR.space gói miễn phí: 1 MB / ảnh

/** Thu nhỏ ảnh chụp (thường vài MB) thành JPEG dưới 1 MB trước khi gửi OCR. */
async function shrinkImage(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 2000 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  for (const quality of [0.9, 0.8, 0.7, 0.55, 0.4]) {
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
    if (blob && blob.size <= CARD_MAX_BYTES) return blob;
  }
  throw new Error("Ảnh quá lớn, hãy chụp lại gần hơn hoặc cắt bớt");
}

/** Chọn / chụp / kéo thả / dán ảnh danh thiếp, OCR rồi trả kết quả để điền form. */
function CardScanner({ customerId, onResult }: { customerId: number; onResult: (r: ContactOcr) => void }) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  useEffect(() => () => void (preview && URL.revokeObjectURL(preview)), [preview]);
  const scan = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", await shrinkImage(file), "card.jpg");
      return (await api.post<ContactOcr>(`/customers/${customerId}/contacts/ocr`, body)).data;
    },
    onSuccess: (r) => {
      onResult(r);
      if (r.full_name || r.email || r.phone) toast.success("Đã điền từ danh thiếp, kiểm tra lại trước khi lưu");
      else toast.error("Không nhận ra thông tin trên ảnh, hãy nhập tay");
    },
    onError: toast.error,
  });
  const pick = (files: Iterable<File>) => {
    const file = Array.from(files).find((f) => f.type.startsWith("image/"));
    if (!file) return;
    setPreview(URL.createObjectURL(file));
    scan.mutate(file);
  };

  return (
    <div className="space-y-2">
      <button
        type="button"
        disabled={scan.isPending}
        onClick={() => input.current?.click()}
        onPaste={(e) => {
          if (e.clipboardData.files.length) {
            e.preventDefault();
            pick(e.clipboardData.files);
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          pick(e.dataTransfer.files);
        }}
        title="Bấm để chọn / chụp ảnh, kéo thả, hoặc bấm vào ô rồi Ctrl+V để dán ảnh"
        className={cn(
          "flex w-full items-center gap-3 rounded-lg border border-dashed border-line-strong p-3 text-left",
          "text-sm text-ink-3 transition-colors hover:border-brand hover:text-brand focus:border-brand focus:text-brand",
          "disabled:cursor-wait",
          over && "border-brand bg-brand-soft text-brand",
        )}
      >
        {preview ? (
          // eslint-disable-next-line @next/next/no-img-element -- ảnh blob cục bộ
          <img src={preview} alt="Danh thiếp" className="h-14 w-24 shrink-0 rounded object-cover" />
        ) : (
          <span className="grid h-14 w-24 shrink-0 place-items-center rounded bg-subtle">
            <ScanLine className="size-6" />
          </span>
        )}
        <span className="min-w-0">
          <span className="flex items-center gap-1.5 font-medium text-ink-2">
            {scan.isPending && <Loader2 className="size-4 animate-spin" />}
            {scan.isPending ? "Đang đọc danh thiếp…" : "Quét danh thiếp để tự điền"}
          </span>
          <span className="block text-xs">Chọn / chụp ảnh, kéo thả hoặc dán (Ctrl+V)</span>
        </span>
      </button>
      <input
        ref={input}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => {
          pick(e.target.files ?? []);
          e.target.value = "";
        }}
      />
      {scan.data?.text && (
        <details className="text-xs text-ink-3">
          <summary className="cursor-pointer select-none">Chữ đọc được từ ảnh</summary>
          <pre className="mt-1 max-h-40 overflow-auto rounded-md bg-subtle p-2 font-sans whitespace-pre-wrap">
            {scan.data.text}
          </pre>
        </details>
      )}
    </div>
  );
}

function ContactModal({ customer, contact, onClose }: { customer: Customer; contact?: Contact; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const editing = !!contact;
  const [form, setForm] = useState({
    full_name: contact?.full_name ?? "",
    position: contact?.position ?? "",
    email: contact?.email ?? "",
    phone: contact?.phone ?? "",
    is_primary: contact?.is_primary ?? false,
  });
  const set = (k: "full_name" | "position" | "email" | "phone", v: string) => setForm((f) => ({ ...f, [k]: v }));
  const save = useMutation({
    mutationFn: async () => {
      const url = `/customers/${customer.id}/contacts`;
      if (!editing) return api.post(url, clean(form));
      // Sửa: ô để trống = xoá giá trị cũ
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === "" ? null : v]));
      return api.patch(`${url}/${contact.id}`, body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["customers", customer.id, "contacts"] });
      toast.success(editing ? "Đã lưu người liên hệ" : "Đã thêm người liên hệ");
      onClose();
    },
    onError: toast.error,
  });

  const text = (key: "full_name" | "position" | "email" | "phone", label: string, type = "text") => (
    <Field label={label} required={key === "full_name"}>
      {(id) => <Input id={id} type={type} value={form[key]} onChange={(e) => set(key, e.target.value)} />}
    </Field>
  );

  return (
    <Modal
      open
      onClose={onClose}
      title={editing ? `Sửa ${contact.full_name}` : "Người liên hệ mới"}
      description={customer.name}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button
            variant="primary"
            type="submit"
            form="contact-form"
            loading={save.isPending}
            disabled={!form.full_name.trim()}
          >
            Lưu
          </Button>
        </>
      }
    >
      <form
        id="contact-form"
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (form.full_name.trim()) save.mutate();
        }}
      >
        {!editing && (
          <div className="sm:col-span-2">
            <CardScanner
              customerId={customer.id}
              onResult={(r) =>
                setForm((f) => ({
                  ...f,
                  full_name: r.full_name ?? f.full_name,
                  position: r.position ?? f.position,
                  email: r.email ?? f.email,
                  phone: r.phone ?? f.phone,
                }))
              }
            />
          </div>
        )}
        {text("full_name", "Họ tên")}
        {text("position", "Chức vụ")}
        {text("email", "Email", "email")}
        {text("phone", "Điện thoại", "tel")}
        <Checkbox
          label="Đầu mối chính"
          className="sm:col-span-2"
          checked={form.is_primary}
          onChange={(e) => setForm((f) => ({ ...f, is_primary: e.target.checked }))}
        />
      </form>
    </Modal>
  );
}

function Contacts({ customer }: { customer: Customer }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useAuth();
  const key = ["customers", customer.id, "contacts"];
  const [modal, setModal] = useState<{ contact?: Contact } | null>(null);
  const contacts = useQuery({
    queryKey: key,
    queryFn: async () => (await api.get<Contact[]>(`/customers/${customer.id}/contacts`)).data,
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<Contact> }) =>
      api.patch(`/customers/${customer.id}/contacts/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
    onError: toast.error,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/customers/${customer.id}/contacts/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: key });
      toast.success("Đã xoá người liên hệ");
    },
    onError: toast.error,
  });
  const canEdit = can("customer.update");

  return (
    <div className="space-y-3">
      {contacts.isPending ? (
        <Spinner />
      ) : !contacts.data?.length ? (
        <p className="text-sm text-ink-3">Chưa có người liên hệ.</p>
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {contacts.data.map((c) => (
            <li key={c.id} className="flex items-center gap-1 px-3 py-2.5 text-sm">
              <div className="min-w-0 flex-1 pr-2">
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
                    <a href={`tel:${c.phone}`} className="inline-flex items-center gap-1 hover:text-brand">
                      <Phone className="size-3" /> {c.phone}
                    </a>
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
                  <IconButton label="Sửa người liên hệ" onClick={() => setModal({ contact: c })}>
                    <Pencil className="size-4" />
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
        <Button size="sm" icon={<UserPlus className="size-3.5" />} onClick={() => setModal({})}>
          Thêm người liên hệ
        </Button>
      )}
      {modal && <ContactModal customer={customer} contact={modal.contact} onClose={() => setModal(null)} />}
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
