"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Lock, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { ActivityFeed } from "@/components/activity-feed";
import { useProjectActivityResolver } from "@/lib/activity-resolver";
import { ImageTextEditor } from "@/components/project/image-text-editor";
import { RequirementFormModal } from "@/components/project/requirement-form";
import { WorkItemModal } from "@/components/project/work-item-modal";
import { PASTE_HINT, RichText, useInlineImages } from "@/components/text-images";
import { Badge, MetaBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox, Field, Textarea } from "@/components/ui/form";
import { Card, CardHeader, Empty, ProgressBar, Spinner, UserChip } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { useMembers, useProjectId, useProjectPerms } from "@/lib/hooks";
import {
  APPROVAL_STATUSES,
  PRIORITY,
  REQUIREMENT_SOURCE,
  REQUIREMENT_STATUS,
  REQUIREMENT_TRANSITIONS,
  REQUIREMENT_TYPE,
  WORK_ITEM_STATUS,
  WORK_ITEM_TYPE,
} from "@/lib/labels";
import type {
  ActivityLog,
  Comment,
  Page,
  RequirementDetail,
  RequirementStatus,
  StatusHistory,
  WorkItem,
} from "@/lib/types";
import { cn, daysUntil, fmtDate, fmtDateTime, fmtHours, fmtRelative, num } from "@/lib/utils";

function StatusChangeModal({
  pid,
  req,
  target,
  onClose,
}: {
  pid: number;
  req: RequirementDetail;
  target: RequirementStatus;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const rejecting = target === "rejected";
  const images = useInlineImages(pid, [note]);
  const mutation = useMutation({
    mutationFn: () =>
      api.post(`/projects/${pid}/requirements/${req.id}/status`, {
        status: target,
        note: note || null,
        rejected_reason: rejecting ? reason : null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", pid, "requirements"] });
      toast.success(`Đã chuyển sang "${REQUIREMENT_STATUS[target].label}"`);
      onClose();
    },
    onError: toast.error,
  });
  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={
        <span className="flex items-center gap-2">
          Chuyển trạng thái <MetaBadge meta={REQUIREMENT_STATUS[target]} />
        </span>
      }
      description={`${req.code} · ${req.title}`}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button
            variant={rejecting ? "danger" : "primary"}
            loading={mutation.isPending}
            disabled={(rejecting && !reason.trim()) || images.uploading > 0}
            onClick={() => mutation.mutate()}
          >
            Xác nhận
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {rejecting && (
          <Field label="Lý do từ chối" required>
            {(id) => <Textarea id={id} autoFocus value={reason} onChange={(e) => setReason(e.target.value)} />}
          </Field>
        )}
        <Field label="Ghi chú" hint={`Lưu vào lịch sử trạng thái. ${PASTE_HINT}`}>
          {(id) => (
            <ImageTextEditor
              id={id}
              rows={2}
              autoFocus={!rejecting}
              placeholder="vd: Khách hàng xác nhận qua email ngày…"
              value={note}
              onChange={setNote}
              source={images.source}
            />
          )}
        </Field>
      </div>
    </Modal>
  );
}

function Comments({ pid, rid }: { pid: number; rid: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useProjectPerms(pid);
  const [content, setContent] = useState("");
  const [internal, setInternal] = useState(false);
  const images = useInlineImages(pid, [content]);
  const canSend = !!content.trim() && images.uploading === 0;
  const key = ["project", pid, "requirements", rid, "comments"];
  const comments = useQuery({
    queryKey: key,
    queryFn: async () => (await api.get<Comment[]>(`/projects/${pid}/requirements/${rid}/comments`)).data,
  });
  const add = useMutation({
    mutationFn: () =>
      api.post(`/projects/${pid}/requirements/${rid}/comments`, { content: content.trim(), is_internal: internal }),
    onSuccess: () => {
      setContent("");
      qc.invalidateQueries({ queryKey: key });
    },
    onError: toast.error,
  });

  return (
    <Card>
      <CardHeader title={`Trao đổi (${comments.data?.length ?? 0})`} />
      {comments.isPending ? (
        <Spinner />
      ) : (
        <ul className="divide-y divide-line">
          {comments.data?.map((c) => (
            <li key={c.id} className={cn("px-4 py-3", c.is_internal && "bg-amber-50/50")}>
              <div className="mb-1 flex items-center gap-2 text-[13px]">
                <UserChip id={c.user_id} name={c.user_name} />
                <time className="text-ink-3" title={fmtDateTime(c.created_at)}>
                  {fmtRelative(c.created_at)}
                </time>
                {c.is_internal && (
                  <Badge tone="amber">
                    <Lock className="size-3" /> Nội bộ
                  </Badge>
                )}
              </div>
              <RichText pid={pid} text={c.content} className="pl-8 text-sm" />
            </li>
          ))}
        </ul>
      )}
      {can("requirement.comment") && (
        <form
          className="space-y-2 border-t border-line p-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSend) add.mutate();
          }}
        >
          <ImageTextEditor
            aria-label="Nội dung bình luận"
            rows={2}
            placeholder="Viết bình luận… (dán ảnh bằng Ctrl+V, gửi bằng Ctrl+Enter)"
            value={content}
            onChange={setContent}
            source={images.source}
            onSubmit={() => canSend && add.mutate()}
          />
          <div className="flex items-center justify-between gap-2">
            {can("requirement.view_internal") ? (
              <Checkbox
                label="Chỉ nội bộ (khách hàng không thấy)"
                checked={internal}
                onChange={(e) => setInternal(e.target.checked)}
              />
            ) : (
              <span />
            )}
            <Button type="submit" size="sm" variant="primary" loading={add.isPending} disabled={!canSend}>
              Gửi
            </Button>
          </div>
        </form>
      )}
    </Card>
  );
}

function HistoryTabs({ pid, rid }: { pid: number; rid: number }) {
  const resolve = useProjectActivityResolver(pid);
  const [tab, setTab] = useState<"status" | "activity">("status");
  const history = useQuery({
    queryKey: ["project", pid, "requirements", rid, "history"],
    queryFn: async () => (await api.get<StatusHistory[]>(`/projects/${pid}/requirements/${rid}/history`)).data,
  });
  const activity = useQuery({
    queryKey: ["project", pid, "requirements", rid, "activity"],
    queryFn: async () =>
      (await api.get<Page<ActivityLog>>(`/projects/${pid}/requirements/${rid}/activity`, { params: { size: 100 } })).data,
    enabled: tab === "activity",
  });

  return (
    <Card>
      <div className="flex gap-1 border-b border-line px-2" role="tablist">
        {(
          [
            ["status", "Lịch sử trạng thái"],
            ["activity", "Nhật ký thay đổi"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2.5 text-[13px] font-medium",
              tab === k ? "border-brand text-brand" : "border-transparent text-ink-3 hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "status" ? (
        history.isPending ? (
          <Spinner />
        ) : (
          <ol className="relative space-y-4 px-6 py-4">
            {history.data?.map((h) => (
              <li key={h.id} className="relative border-l-2 border-line pb-1 pl-5">
                <span className="absolute top-1 -left-[7px] size-3 rounded-full border-2 border-surface bg-brand" />
                <div className="flex flex-wrap items-center gap-1.5 text-sm">
                  {h.from_status && (
                    <>
                      <MetaBadge meta={REQUIREMENT_STATUS[h.from_status]} />
                      <span className="text-ink-3">→</span>
                    </>
                  )}
                  <MetaBadge meta={REQUIREMENT_STATUS[h.to_status]} />
                </div>
                <p className="mt-1 text-xs text-ink-3">
                  {h.changed_by_name ?? "Hệ thống"} · {fmtDateTime(h.changed_at)}
                </p>
                {h.note && <RichText pid={pid} text={h.note} className="mt-1 text-sm text-ink-2" />}
              </li>
            ))}
          </ol>
        )
      ) : activity.isPending ? (
        <Spinner />
      ) : (
        <ActivityFeed items={activity.data?.items ?? []} showEntity={false} resolve={resolve} />
      )}
    </Card>
  );
}

export default function RequirementDetailPage() {
  const pid = useProjectId();
  const rid = Number(useParams<{ rid: string }>().rid);
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useProjectPerms(pid);
  const { byId } = useMembers(pid);
  const [editing, setEditing] = useState(false);
  const [target, setTarget] = useState<RequirementStatus | null>(null);
  const [newItem, setNewItem] = useState(false);
  const [openItem, setOpenItem] = useState<WorkItem | null>(null);

  const req = useQuery({
    queryKey: ["project", pid, "requirements", rid],
    queryFn: async () => (await api.get<RequirementDetail>(`/projects/${pid}/requirements/${rid}`)).data,
  });
  const items = useQuery({
    queryKey: ["project", pid, "work-items", { requirement_id: rid }],
    queryFn: async () =>
      (await api.get<Page<WorkItem>>(`/projects/${pid}/work-items`, { params: { requirement_id: rid, size: 200 } })).data
        .items,
    enabled: can("work_item.view"),
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/projects/${pid}/requirements/${rid}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", pid, "requirements"] });
      toast.success("Đã xoá yêu cầu");
      router.push(`/projects/${pid}/requirements`);
    },
    onError: toast.error,
  });

  if (req.isPending) return <Spinner />;
  if (req.isError) return <Empty title="Không mở được yêu cầu" description={errorMessage(req.error)} />;
  const r = req.data;
  const transitions = REQUIREMENT_TRANSITIONS[r.status].filter((s) =>
    APPROVAL_STATUSES.includes(s) ? can("requirement.approve") : can("requirement.update"),
  );
  const left = daysUntil(r.due_date);
  const isOpen = !["done", "closed", "cancelled", "rejected"].includes(r.status);
  const progress = r.stats.work_item_count ? (r.stats.work_item_done / r.stats.work_item_count) * 100 : 0;

  return (
    <>
      <Link
        href={`/projects/${pid}/requirements`}
        className="mb-3 inline-flex items-center gap-1 text-[13px] text-ink-3 hover:text-ink"
      >
        <ArrowLeft className="size-3.5" /> Danh sách yêu cầu
      </Link>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card className="p-5">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-ink-3">{r.code}</span>
              <MetaBadge meta={REQUIREMENT_STATUS[r.status]} />
              <MetaBadge meta={PRIORITY[r.priority]} dot={false} />
              <Badge>{REQUIREMENT_TYPE[r.type]}</Badge>
              {r.stats.is_overdue && <Badge tone="red">Quá hạn</Badge>}
            </div>
            <h2 className="text-lg font-semibold">{r.title}</h2>
            {r.description ? (
              <RichText pid={pid} text={r.description} className="mt-3 text-sm leading-relaxed text-ink-2" />
            ) : (
              <p className="mt-3 text-sm text-ink-3 italic">Chưa có mô tả.</p>
            )}
            {r.acceptance_criteria && (
              <div className="mt-4 rounded-lg bg-subtle px-4 py-3">
                <p className="mb-1 text-xs font-semibold tracking-wide text-ink-3 uppercase">Tiêu chí nghiệm thu</p>
                <RichText pid={pid} text={r.acceptance_criteria} className="text-sm" />
              </div>
            )}
            {r.status === "rejected" && r.rejected_reason && (
              <div className="mt-4 rounded-lg bg-danger-soft px-4 py-3 text-sm text-red-800">
                <span className="font-medium">Lý do từ chối:</span> {r.rejected_reason}
              </div>
            )}
          </Card>

          {can("work_item.view") && (
            <Card>
              <CardHeader
                title={`Công việc thực hiện (${r.stats.work_item_done}/${r.stats.work_item_count})`}
                action={
                  can("work_item.create") && (
                    <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => setNewItem(true)}>
                      Tạo công việc
                    </Button>
                  )
                }
              />
              {r.stats.work_item_count > 0 && <ProgressBar value={progress} className="h-1 rounded-none" />}
              {!items.data?.length ? (
                <p className="px-4 py-5 text-sm text-ink-3">Chưa tách thành công việc nào.</p>
              ) : (
                <ul className="divide-y divide-line">
                  {items.data.map((w) => (
                    <li key={w.id}>
                      <button
                        type="button"
                        onClick={() => setOpenItem(w)}
                        className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm hover:bg-subtle/60"
                      >
                        <MetaBadge meta={WORK_ITEM_TYPE[w.type]} dot={false} />
                        <span className="font-mono text-xs text-ink-3">{w.code}</span>
                        <span className="min-w-0 flex-1 truncate">{w.title}</span>
                        <UserChip id={w.assignee_id} name={w.assignee_id ? byId.get(w.assignee_id)?.full_name : null} />
                        <MetaBadge meta={WORK_ITEM_STATUS[w.status]} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}

          <Comments pid={pid} rid={rid} />
          <HistoryTabs pid={pid} rid={rid} />
        </div>

        <div className="space-y-6">
          {transitions.length > 0 && (
            <Card>
              <CardHeader title="Chuyển trạng thái" />
              <div className="flex flex-wrap gap-2 p-4">
                {transitions.map((s) => (
                  <Button
                    key={s}
                    size="sm"
                    variant={s === "approved" ? "primary" : s === "rejected" ? "danger" : "secondary"}
                    onClick={() => setTarget(s)}
                  >
                    {REQUIREMENT_STATUS[s].label}
                  </Button>
                ))}
              </div>
            </Card>
          )}

          <Card>
            <CardHeader
              title="Chi tiết"
              action={
                <div className="flex gap-1">
                  {can("requirement.update") && (
                    <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(true)}>
                      Sửa
                    </Button>
                  )}
                  {can("requirement.delete") && (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label="Xoá yêu cầu"
                      className="text-danger hover:bg-danger-soft hover:text-danger"
                      icon={<Trash2 className="size-3.5" />}
                      loading={remove.isPending}
                      onClick={() => confirm(`Xoá yêu cầu ${r.code}?`) && remove.mutate()}
                    />
                  )}
                </div>
              }
            />
            <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-2.5 px-4 py-4 text-sm">
              <dt className="text-ink-3">Phụ trách</dt>
              <dd>
                <UserChip id={r.assignee_id} name={r.assignee_id ? byId.get(r.assignee_id)?.full_name : null} />
              </dd>
              <dt className="text-ink-3">Nguồn</dt>
              <dd>{REQUIREMENT_SOURCE[r.source]}</dd>
              <dt className="text-ink-3">Tiếp nhận</dt>
              <dd className="tabular-nums">{fmtDateTime(r.received_at)}</dd>
              <dt className="text-ink-3">KH mong muốn</dt>
              <dd className="tabular-nums">{fmtDate(r.expected_date)}</dd>
              <dt className="text-ink-3">Hạn cam kết</dt>
              <dd className="tabular-nums">
                {fmtDate(r.due_date)}
                {left !== null && isOpen && (
                  <span className={cn("ml-1.5 text-xs", left < 0 ? "text-danger" : "text-ink-3")}>
                    ({left < 0 ? `trễ ${-left} ngày` : `còn ${left} ngày`})
                  </span>
                )}
              </dd>
              <dt className="text-ink-3">Ước lượng</dt>
              <dd>{r.estimated_hours != null ? fmtHours(r.estimated_hours) : "—"}</dd>
              <dt className="text-ink-3">Đã log</dt>
              <dd>
                {fmtHours(r.stats.logged_hours)}
                {r.estimated_hours != null && num(r.estimated_hours) > 0 && (
                  <span className="ml-1.5 text-xs text-ink-3">
                    ({Math.round((num(r.stats.logged_hours) / num(r.estimated_hours)) * 100)}%)
                  </span>
                )}
              </dd>
              <dt className="text-ink-3">Giá trị KD</dt>
              <dd>{r.business_value ?? "—"}</dd>
              <dt className="text-ink-3">Phát hành</dt>
              <dd>{r.target_release ?? "—"}</dd>
              {r.approved_at && (
                <>
                  <dt className="text-ink-3">Duyệt bởi</dt>
                  <dd>
                    {(r.approved_by && byId.get(r.approved_by)?.full_name) ?? "—"}
                    <span className="block text-xs text-ink-3">{fmtDateTime(r.approved_at)}</span>
                  </dd>
                </>
              )}
              {r.tags.length > 0 && (
                <>
                  <dt className="text-ink-3">Tag</dt>
                  <dd className="flex flex-wrap gap-1">
                    {r.tags.map((t) => (
                      <span key={t} className="rounded bg-subtle px-1.5 py-0.5 text-xs">
                        {t}
                      </span>
                    ))}
                  </dd>
                </>
              )}
            </dl>
          </Card>
        </div>
      </div>

      {editing && <RequirementFormModal open pid={pid} requirement={r} onClose={() => setEditing(false)} />}
      {target && <StatusChangeModal pid={pid} req={r} target={target} onClose={() => setTarget(null)} />}
      {newItem && (
        <WorkItemModal
          pid={pid}
          defaults={{ requirement_id: r.id, title: r.title, type: "story" }}
          onClose={() => setNewItem(false)}
        />
      )}
      {openItem && <WorkItemModal pid={pid} item={openItem} onClose={() => setOpenItem(null)} />}
    </>
  );
}
