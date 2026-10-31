"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, ExternalLink, Mail, MapPin, Pencil, Phone, Reply, Trash2 } from "lucide-react";
import { useState } from "react";

import { EnumSelect, MemberSelect } from "@/components/project/selects";
import { MetaBadge } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { ExpandableText } from "@/components/ui/expandable-text";
import { Field, Input, Textarea } from "@/components/ui/form";
import { Empty, Spinner } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { useProjectPerms } from "@/lib/hooks";
import { CRM_INQUIRY_TYPE, CRM_STATUS } from "@/lib/labels";
import type { CrmContact, CrmContactStatus, CrmEmail, Page } from "@/lib/types";
import { cn, fmtDateTime, fmtRelative, num } from "@/lib/utils";

/** Mọi query CRM của dự án nằm dưới key này: sửa gì thì invalidate cả nhóm. */
export const crmKey = (pid: number) => ["project", pid, "crm"] as const;

export function useInvalidateCrm(pid: number) {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: crmKey(pid) });
}

/** Tên hiển thị của khách: họ tên, không có thì email. */
export function contactName(c: Pick<CrmContact, "full_name" | "email">) {
  return c.full_name || c.email;
}

const PROFILE_FIELDS = [
  { key: "email", label: "Email người gửi", type: "email", required: true },
  { key: "full_name", label: "Họ tên" },
  { key: "phone", label: "Điện thoại" },
  { key: "contact_email", label: "Email liên hệ khác", type: "email" },
  { key: "company", label: "Công ty", span: true },
  { key: "address", label: "Địa chỉ", span: true },
] as const;
type ProfileKey = (typeof PROFILE_FIELDS)[number]["key"];

/** Thêm khách tay / sửa thông tin khách. */
export function CrmContactFormModal({
  pid,
  contact,
  onClose,
  onSaved,
}: {
  pid: number;
  contact?: CrmContact;
  onClose: () => void;
  onSaved?: (c: CrmContact) => void;
}) {
  const toast = useToast();
  const invalidate = useInvalidateCrm(pid);
  const editing = !!contact;
  const [form, setForm] = useState<Record<ProfileKey, string>>(() =>
    Object.fromEntries(PROFILE_FIELDS.map((f) => [f.key, contact?.[f.key] ?? ""])) as Record<ProfileKey, string>,
  );
  const [extra, setExtra] = useState({ status: "new" as CrmContactStatus, assignee_id: null as number | null, note: "" });

  const save = useMutation({
    mutationFn: async () => {
      // Ô để trống = xoá giá trị cũ
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null]));
      if (editing) return (await api.patch<CrmContact>(`/projects/${pid}/crm/contacts/${contact.id}`, body)).data;
      return (
        await api.post<CrmContact>(`/projects/${pid}/crm/contacts`, { ...body, ...extra, note: extra.note || null })
      ).data;
    },
    onSuccess: (c) => {
      invalidate();
      toast.success(editing ? "Đã lưu thông tin khách" : "Đã thêm khách liên hệ");
      onSaved?.(c);
      onClose();
    },
    onError: toast.error,
  });
  const valid = form.email.trim().length > 0;

  return (
    <Modal
      open
      onClose={onClose}
      title={editing ? `Sửa ${contactName(contact)}` : "Thêm khách liên hệ"}
      description={editing ? undefined : "Email từ n8n gửi về sau sẽ tự gộp vào khách có cùng email người gửi."}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button variant="primary" type="submit" form="crm-contact-form" loading={save.isPending} disabled={!valid}>
            Lưu
          </Button>
        </>
      }
    >
      <form
        id="crm-contact-form"
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) save.mutate();
        }}
      >
        {PROFILE_FIELDS.map((f) => (
          <Field
            key={f.key}
            label={f.label}
            required={"required" in f && f.required}
            className={cn("span" in f && f.span && "sm:col-span-2")}
          >
            {(id) => (
              <Input
                id={id}
                type={"type" in f ? f.type : "text"}
                value={form[f.key]}
                onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))}
              />
            )}
          </Field>
        ))}
        {!editing && (
          <>
            <Field label="Trạng thái">
              {(id) => (
                <EnumSelect
                  id={id}
                  options={CRM_STATUS}
                  value={extra.status}
                  onChange={(v) => v && setExtra((s) => ({ ...s, status: v }))}
                />
              )}
            </Field>
            <Field label="Người phụ trách">
              {(id) => (
                <MemberSelect
                  id={id}
                  pid={pid}
                  value={extra.assignee_id}
                  onChange={(v) => setExtra((s) => ({ ...s, assignee_id: v }))}
                />
              )}
            </Field>
            <Field label="Ghi chú" className="sm:col-span-2">
              {(id) => (
                <Textarea id={id} value={extra.note} onChange={(e) => setExtra((s) => ({ ...s, note: e.target.value }))} />
              )}
            </Field>
          </>
        )}
      </form>
    </Modal>
  );
}

function InfoLine({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-2 text-sm text-ink-2">
      <span className="mt-0.5 shrink-0 text-ink-3">{icon}</span>
      <span className="min-w-0 break-words">{children}</span>
    </p>
  );
}

const NEED_FIELDS = [
  ["product_type", "Sản phẩm"],
  ["quantity", "Số lượng"],
  ["budget", "Ngân sách"],
  ["deadline", "Thời hạn"],
] as const;

/** Một email khách gửi: nhu cầu AI trích xuất + nội dung gốc. */
export function CrmEmailCard({
  email,
  canDelete,
  onDelete,
}: {
  email: CrmEmail;
  canDelete: boolean;
  onDelete: () => void;
}) {
  const needs = NEED_FIELDS.filter(([k]) => email[k]);
  const reply = `mailto:${email.customer_email}?subject=${encodeURIComponent(`Re: ${email.subject ?? ""}`)}`;
  return (
    <article className="rounded-lg border border-line p-3.5">
      <header className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-medium break-words">{email.subject || "(Không có tiêu đề)"}</h4>
          <p className="mt-0.5 text-xs text-ink-3">
            {fmtDateTime(email.received_at)} · {email.customer_name || email.customer_email}
            {email.ai_confidence !== null && <> · AI tin cậy {Math.round(num(email.ai_confidence) * 100)}%</>}
          </p>
        </div>
        <MetaBadge meta={CRM_INQUIRY_TYPE[email.inquiry_type]} />
        <div className="flex items-center">
          <a
            href={reply}
            title="Trả lời bằng ứng dụng email"
            aria-label="Trả lời"
            className="inline-flex size-8 items-center justify-center rounded-lg text-ink-3 hover:bg-subtle hover:text-ink"
          >
            <Reply className="size-4" />
          </a>
          {email.email_thread_id && (
            <a
              href={`https://mail.google.com/mail/u/0/#all/${email.email_thread_id}`}
              target="_blank"
              rel="noreferrer"
              title="Mở trong Gmail"
              aria-label="Mở trong Gmail"
              className="inline-flex size-8 items-center justify-center rounded-lg text-ink-3 hover:bg-subtle hover:text-ink"
            >
              <ExternalLink className="size-4" />
            </a>
          )}
          {canDelete && (
            <IconButton label="Xoá email" onClick={() => confirm("Xoá email này khỏi CRM?") && onDelete()}>
              <Trash2 className="size-4" />
            </IconButton>
          )}
        </div>
      </header>

      {email.summary && <p className="mt-2 text-sm">{email.summary}</p>}
      {needs.length > 0 && (
        <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1.5 rounded-md bg-subtle/70 px-3 py-2 text-[13px] sm:grid-cols-4">
          {needs.map(([k, label]) => (
            <div key={k} className="min-w-0">
              <dt className="text-xs text-ink-3">{label}</dt>
              <dd className="break-words">{email[k]}</dd>
            </div>
          ))}
        </dl>
      )}
      {email.specifications && (
        <div className="mt-2 text-[13px]">
          <span className="text-xs text-ink-3">Quy cách: </span>
          <ExpandableText text={email.specifications} lines={2} className="inline" />
        </div>
      )}
      {email.content && (
        <details className="mt-2 text-[13px]">
          <summary className="cursor-pointer text-xs font-medium text-ink-3 select-none hover:text-ink">
            Nội dung email gốc
          </summary>
          <pre className="mt-1.5 max-h-72 overflow-auto rounded-md bg-subtle p-2.5 font-sans whitespace-pre-wrap">
            {email.content}
          </pre>
        </details>
      )}
    </article>
  );
}

/** Chi tiết khách liên hệ: thông tin, trạng thái theo dõi, phụ trách, ghi chú, các email đã gửi. */
export function CrmContactModal({ pid, contactId, onClose }: { pid: number; contactId: number; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateCrm(pid);
  const { can } = useProjectPerms(pid);
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState<string | null>(null); // null = chưa sửa

  const base = `/projects/${pid}/crm`;
  const contact = useQuery({
    queryKey: [...crmKey(pid), "contact", contactId],
    queryFn: async () => (await api.get<CrmContact>(`${base}/contacts/${contactId}`)).data,
  });
  const emails = useQuery({
    queryKey: [...crmKey(pid), "emails", { contact_id: contactId }],
    queryFn: async () =>
      (await api.get<Page<CrmEmail>>(`${base}/emails`, { params: { contact_id: contactId, size: 200 } })).data,
  });

  const update = useMutation({
    mutationFn: async (body: Partial<Pick<CrmContact, "status" | "assignee_id" | "note">>) =>
      (await api.patch<CrmContact>(`${base}/contacts/${contactId}`, body)).data,
    onSuccess: (_, body) => {
      invalidate();
      if ("note" in body) setNote(null);
      toast.success("Đã cập nhật");
    },
    onError: toast.error,
  });
  const removeEmail = useMutation({
    mutationFn: (id: number) => api.delete(`${base}/emails/${id}`),
    onSuccess: () => {
      invalidate();
      toast.success("Đã xoá email");
    },
    onError: toast.error,
  });
  const removeContact = useMutation({
    mutationFn: () => api.delete(`${base}/contacts/${contactId}`),
    onSuccess: () => {
      invalidate();
      toast.success("Đã xoá khách liên hệ");
      onClose();
    },
    onError: toast.error,
  });

  const c = contact.data;
  const canUpdate = can("crm.update");

  return (
    <>
      <Modal
        open={!editing}
        onClose={onClose}
        size="xl"
        title={c ? contactName(c) : "Khách liên hệ"}
        description={c?.company ?? undefined}
      >
        {contact.isPending ? (
          <Spinner />
        ) : contact.isError ? (
          <Empty title="Không mở được khách liên hệ" description={errorMessage(contact.error)} />
        ) : (
          c && (
            <div className="grid gap-5 lg:grid-cols-[18rem_1fr]">
              <aside className="space-y-4">
                <div className="space-y-2">
                  <InfoLine icon={<Mail className="size-4" />}>
                    <a href={`mailto:${c.email}`} className="hover:text-brand hover:underline">
                      {c.email}
                    </a>
                    {c.contact_email && c.contact_email !== c.email && (
                      <span className="block text-ink-3">Khác: {c.contact_email}</span>
                    )}
                  </InfoLine>
                  {c.phone && (
                    <InfoLine icon={<Phone className="size-4" />}>
                      <a href={`tel:${c.phone}`} className="hover:text-brand hover:underline">
                        {c.phone}
                      </a>
                    </InfoLine>
                  )}
                  {c.company && <InfoLine icon={<Building2 className="size-4" />}>{c.company}</InfoLine>}
                  {c.address && <InfoLine icon={<MapPin className="size-4" />}>{c.address}</InfoLine>}
                  <p className="text-xs text-ink-3">
                    {c.source === "manual" ? "Nhập tay" : `Nguồn: ${c.source}`} · tạo {fmtRelative(c.created_at)}
                  </p>
                </div>

                <Field label="Trạng thái">
                  {(id) => (
                    <EnumSelect
                      id={id}
                      options={CRM_STATUS}
                      value={c.status}
                      disabled={!canUpdate || update.isPending}
                      onChange={(v) => v && v !== c.status && update.mutate({ status: v })}
                    />
                  )}
                </Field>
                <Field label="Người phụ trách">
                  {(id) => (
                    <MemberSelect
                      id={id}
                      pid={pid}
                      value={c.assignee_id}
                      disabled={!canUpdate || update.isPending}
                      onChange={(v) => update.mutate({ assignee_id: v })}
                    />
                  )}
                </Field>
                <Field label="Ghi chú theo dõi">
                  {(id) => (
                    <Textarea
                      id={id}
                      rows={4}
                      placeholder={canUpdate ? "Đã gọi điện, hẹn gửi mẫu…" : undefined}
                      value={note ?? c.note ?? ""}
                      disabled={!canUpdate}
                      onChange={(e) => setNote(e.target.value)}
                    />
                  )}
                </Field>
                {note !== null && note !== (c.note ?? "") && (
                  <div className="flex justify-end gap-2">
                    <Button size="sm" onClick={() => setNote(null)}>
                      Huỷ
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      loading={update.isPending}
                      onClick={() => update.mutate({ note: note.trim() || null })}
                    >
                      Lưu ghi chú
                    </Button>
                  </div>
                )}

                <div className="flex flex-wrap gap-2 border-t border-line pt-4">
                  {canUpdate && (
                    <Button size="sm" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(true)}>
                      Sửa thông tin
                    </Button>
                  )}
                  {can("crm.delete") && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-danger hover:bg-danger-soft hover:text-danger"
                      icon={<Trash2 className="size-3.5" />}
                      loading={removeContact.isPending}
                      onClick={() =>
                        confirm(`Xoá ${contactName(c)} và toàn bộ ${c.email_count} email của khách?`) &&
                        removeContact.mutate()
                      }
                    >
                      Xoá khách
                    </Button>
                  )}
                </div>
              </aside>

              <section className="min-w-0">
                <h3 className="mb-2.5 text-sm font-semibold">
                  Email đã nhận <span className="font-normal text-ink-3">({c.email_count})</span>
                </h3>
                {emails.isPending ? (
                  <Spinner />
                ) : !emails.data?.items.length ? (
                  <Empty
                    className="rounded-lg border border-dashed border-line"
                    title="Chưa có email"
                    description="Email từ khách này do n8n gửi về sẽ hiện ở đây."
                  />
                ) : (
                  <div className="space-y-3">
                    {emails.data.items.map((e) => (
                      <CrmEmailCard
                        key={e.id}
                        email={e}
                        canDelete={can("crm.delete")}
                        onDelete={() => removeEmail.mutate(e.id)}
                      />
                    ))}
                  </div>
                )}
              </section>
            </div>
          )
        )}
      </Modal>
      {editing && c && <CrmContactFormModal pid={pid} contact={c} onClose={() => setEditing(false)} />}
    </>
  );
}
