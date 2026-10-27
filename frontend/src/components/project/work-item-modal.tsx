"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, CornerLeftUp, Trash2 } from "lucide-react";
import { useState } from "react";

import { FileAttachments, useFileAttachments } from "@/components/project/file-attachments";
import { ImageTextEditor } from "@/components/project/image-text-editor";
import {
  CATEGORY_LABEL,
  imageMarker,
  textImageSource,
  useWorkItemImages,
  WorkItemImages,
} from "@/components/project/work-item-images";
import { EnumSelect, MultiMemberSelect, SprintSelect } from "@/components/project/selects";
import { Subtasks } from "@/components/project/subtasks";
import { WorkLogModal } from "@/components/project/work-log-form";
import { TextImagesButton, useInlineImages, withoutImages } from "@/components/text-images";
import { Button } from "@/components/ui/button";
import { ExpandableText } from "@/components/ui/expandable-text";
import { Field, Input, Select } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMembers, useProjectPerms, useSprints } from "@/lib/hooks";
import { ACTIVITY_TYPE, PRIORITY, WORK_ITEM_STATUS, WORK_ITEM_TYPE } from "@/lib/labels";
import type {
  AttachmentCategory,
  Page,
  Priority,
  Requirement,
  WorkItem,
  WorkItemStatus,
  WorkItemType,
  WorkLog,
} from "@/lib/types";
import { fmtDate, fmtHours, num } from "@/lib/utils";

type FormState = {
  type: WorkItemType;
  title: string;
  description: string;
  acceptance_criteria: string;
  status: WorkItemStatus;
  priority: Priority;
  story_points: string;
  original_estimate_hours: string;
  remaining_hours: string;
  requirement_id: number | null;
  sprint_id: number | null;
  assignee_ids: number[];
  due_date: string;
  parent_id: number | null;
};

// Ảnh dán vào Mô tả -> Ảnh lỗi, vào Tiêu chí hoàn thành -> Ảnh sau khi sửa; văn bản giữ dấu [Ảnh lỗi: tên file]
const IMAGE_FIELD = { bug: "description", result: "acceptance_criteria" } as const;
const withoutMarker = (text: string, marker: string) =>
  text
    .split("\n")
    .filter((line) => line !== marker)
    .join("\n");

const str = (v: unknown) => (v == null ? "" : String(num(v)));
const numOrNull = (v: string) => (v === "" ? null : Number(v));

function initial(item?: WorkItem, defaults?: Partial<FormState>): FormState {
  return {
    type: item?.type ?? "task",
    title: item?.title ?? "",
    description: item?.description ?? "",
    acceptance_criteria: item?.acceptance_criteria ?? "",
    status: item?.status ?? (defaults?.sprint_id ? "todo" : "backlog"),
    priority: item?.priority ?? "medium",
    story_points: str(item?.story_points),
    original_estimate_hours: str(item?.original_estimate_hours),
    remaining_hours: str(item?.remaining_hours),
    requirement_id: item?.requirement_id ?? null,
    sprint_id: item?.sprint_id ?? null,
    assignee_ids: item?.assignee_ids ?? [],
    due_date: item?.due_date ?? "",
    parent_id: item?.parent_id ?? null,
    ...defaults,
  };
}

/** Tạo mới (không truyền item) hoặc xem / sửa công việc. Render có điều kiện để reset form mỗi lần mở. */
export function WorkItemModal({
  pid,
  item,
  defaults,
  onClose,
}: {
  pid: number;
  item?: WorkItem;
  defaults?: Partial<FormState>;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const { me } = useAuth();
  const { can } = useProjectPerms(pid);
  const { byId } = useMembers(pid);
  const [form, setForm] = useState<FormState>(() => initial(item, defaults));
  const [logOpen, setLogOpen] = useState(false);
  // Mở subtask / công việc cha chồng lên modal hiện tại
  const [related, setRelated] = useState<WorkItem | null>(null);
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));
  const editing = !!item;
  const canEdit = editing ? can("work_item.update") : can("work_item.create");
  const images = useWorkItemImages({
    pid,
    itemId: item?.id,
    canEdit,
    onRemoved: (name, category) => {
      const field = IMAGE_FIELD[category];
      setForm((f) => ({ ...f, [field]: withoutMarker(f[field], imageMarker(category, name)) }));
    },
  });

  const files = useFileAttachments({
    pid,
    base: item ? `/projects/${pid}/work-items/${item.id}` : undefined,
    canEdit,
  });
  // File gắn trong Mô tả / Tiêu chí hoàn thành: dấu [File: ...] trong văn bản, như các ô soạn khác
  const inline = useInlineImages(pid, [form.description, form.acceptance_criteria], "work-items");
  const textSource = (category: AttachmentCategory) => ({
    ...textImageSource(images, category),
    files: inline.source.files,
  });

  const pasteHint = (category: AttachmentCategory) =>
    canEdit
      ? `Dán ảnh (Ctrl+V), kéo thả hoặc bấm "Gắn ảnh" để thêm vào "${CATEGORY_LABEL[category]}"; "Gắn file" để đính kèm tài liệu`
      : undefined;

  const requirements = useQuery({
    queryKey: ["project", pid, "requirements", "open-for-link"],
    queryFn: async () =>
      (
        await api.get<Page<Requirement>>(`/projects/${pid}/requirements`, {
          params: { status: ["approved", "in_progress", "analyzing", "pending_approval", "new"], size: 200, sort: "code" },
        })
      ).data.items,
  });

  // Công việc có thể làm cha: không phải subtask, chưa huỷ, không nằm trong sprint đã kết thúc
  const isSubtask = form.type === "subtask";
  const sprints = useSprints(pid);
  const sprintName = new Map((sprints.data ?? []).map((s) => [s.id, s.name]));
  const closedSprints = new Set(
    (sprints.data ?? []).filter((s) => s.status === "completed" || s.status === "cancelled").map((s) => s.id),
  );
  const candidates = useQuery({
    queryKey: ["project", pid, "work-items", "parent-candidates"],
    queryFn: async () =>
      (
        await api.get<Page<WorkItem>>(`/projects/${pid}/work-items`, {
          params: {
            type: ["epic", "story", "task", "bug"],
            status: ["backlog", "todo", "in_progress", "in_review", "testing", "done"],
            size: 500,
          },
        })
      ).data.items,
    enabled: isSubtask,
  });
  const parentOptions = (candidates.data ?? []).filter(
    (w) =>
      w.id === form.parent_id ||
      (w.id !== item?.id && !w.parent_id && !(w.sprint_id && closedSprints.has(w.sprint_id))),
  );
  // Công việc đang có subtask thì không đổi thành subtask được (chỉ một cấp)
  const typeOptions =
    item && item.subtask_count > 0
      ? (Object.fromEntries(Object.entries(WORK_ITEM_TYPE).filter(([k]) => k !== "subtask")) as typeof WORK_ITEM_TYPE)
      : WORK_ITEM_TYPE;

  /** Chọn công việc cha: sprint theo cha (backlog <-> todo như khi đổi sprint), mặc định cùng yêu cầu khách hàng. */
  function chooseParent(id: number | null) {
    const p = parentOptions.find((w) => w.id === id);
    setForm((f) => {
      if (!p) return { ...f, parent_id: id };
      const sprint_id = p.sprint_id;
      return {
        ...f,
        parent_id: p.id,
        sprint_id,
        status: sprint_id && f.status === "backlog" ? "todo" : !sprint_id && f.status === "todo" ? "backlog" : f.status,
        requirement_id: f.requirement_id ?? p.requirement_id,
      };
    });
  }

  const parent = useQuery({
    queryKey: ["project", pid, "work-items", item?.parent_id],
    queryFn: async () => (await api.get<WorkItem>(`/projects/${pid}/work-items/${item!.parent_id}`)).data,
    enabled: !!item?.parent_id,
  });
  const hasSubtasks = !!item && !item.parent_id && item.subtask_count > 0;

  const logs = useQuery({
    queryKey: ["project", pid, "work-logs", { work_item_id: item?.id }],
    queryFn: async () =>
      (await api.get<Page<WorkLog>>(`/projects/${pid}/work-logs`, { params: { work_item_id: item!.id, size: 100 } })).data,
    enabled: editing && can("work_log.view"),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["project", pid] });
  };

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        type: form.type,
        title: form.title.trim(),
        description: form.description || null,
        acceptance_criteria: form.acceptance_criteria || null,
        status: form.status,
        priority: form.priority,
        story_points: numOrNull(form.story_points),
        original_estimate_hours: numOrNull(form.original_estimate_hours),
        remaining_hours: numOrNull(form.remaining_hours),
        requirement_id: form.requirement_id,
        sprint_id: form.sprint_id,
        assignee_ids: form.assignee_ids,
        due_date: form.due_date || null,
        parent_id: form.parent_id,
      };
      if (editing) {
        // Chỉ gửi trường đã đổi để không đụng quyền giao việc khi không cần
        const before = initial(item) as Record<string, unknown>;
        const changed = Object.fromEntries(
          Object.entries(body).filter(
            ([k]) => JSON.stringify((form as Record<string, unknown>)[k]) !== JSON.stringify(before[k]),
          ),
        );
        return (await api.patch<WorkItem>(`/projects/${pid}/work-items/${item.id}`, changed)).data;
      }
      const created = (await api.post<WorkItem>(`/projects/${pid}/work-items`, body)).data;
      // Ảnh chọn trong lúc tạo: tải lên sau khi có công việc; lỗi ảnh không làm hỏng việc tạo
      const failed = await images.uploadPending(created.id);
      if (failed) toast.error(`${created.code}: ${failed} ảnh tải lên lỗi — mở lại công việc để thử lại`);
      const failedFiles = await files.uploadPending(`/projects/${pid}/work-items/${created.id}`);
      if (failedFiles) toast.error(`${created.code}: ${failedFiles} file tải lên lỗi — mở lại công việc để thử lại`);
      return created;
    },
    onSuccess: (saved) => {
      invalidate();
      toast.success(editing ? `Đã lưu ${saved.code}` : `Đã tạo ${saved.code}`);
      onClose();
    },
    onError: toast.error,
  });

  const remove = useMutation({
    mutationFn: () => api.delete(`/projects/${pid}/work-items/${item!.id}`),
    onSuccess: () => {
      invalidate();
      toast.success(`Đã xoá ${item!.code}`);
      onClose();
    },
    onError: toast.error,
  });

  const loggedTotal = (logs.data?.items ?? []).reduce((s, l) => s + num(l.hours), 0);

  return (
    <>
      <Modal
        open
        onClose={onClose}
        size="lg"
        title={editing ? `${item.code} · ${WORK_ITEM_TYPE[item.type].label}` : "Công việc mới"}
        footer={
          <>
            {editing && can("work_item.delete") && (
              <Button
                variant="ghost"
                className="mr-auto text-danger hover:bg-danger-soft hover:text-danger"
                icon={<Trash2 className="size-4" />}
                loading={remove.isPending}
                onClick={() => confirm(`Xoá ${item.code}?`) && remove.mutate()}
              >
                Xoá
              </Button>
            )}
            {editing && can("work_log.create") && (
              <Button icon={<Clock className="size-4" />} onClick={() => setLogOpen(true)}>
                Ghi log
              </Button>
            )}
            <Button onClick={onClose}>Đóng</Button>
            {canEdit && (
              <Button variant="primary" loading={save.isPending} disabled={!form.title.trim() || inline.uploading > 0 || (isSubtask && !form.parent_id)}
                onClick={() => save.mutate()}>
                {editing ? "Lưu" : "Tạo công việc"}
              </Button>
            )}
          </>
        }
      >
        {parent.data && (
          <button
            type="button"
            onClick={() => setRelated(parent.data)}
            className="mb-4 flex w-full items-center gap-2 rounded-lg bg-subtle px-3 py-2 text-left text-sm hover:bg-brand-soft"
          >
            <CornerLeftUp className="size-4 shrink-0 text-ink-3" />
            <span className="text-ink-3">Subtask của</span>
            <span className="shrink-0 font-mono text-xs text-ink-3">{parent.data.code}</span>
            <span className="truncate font-medium">{parent.data.title}</span>
          </button>
        )}
        <fieldset disabled={!canEdit} className="grid gap-4 sm:grid-cols-6">
          <Field label="Loại" className="sm:col-span-2">
            {(id) => (
              <EnumSelect
                id={id}
                options={typeOptions}
                value={form.type}
                // Bỏ loại subtask thì gỡ luôn công việc cha (backend cũng làm vậy)
                onChange={(v) => v && setForm((f) => ({ ...f, type: v, parent_id: v === "subtask" ? f.parent_id : null }))}
              />
            )}
          </Field>
          <Field label="Tiêu đề" required className="sm:col-span-4">
            {(id) => <Input id={id} autoFocus={!editing} value={form.title} onChange={(e) => set("title", e.target.value)} />}
          </Field>
          {isSubtask && (
            <Field
              label="Công việc cha"
              required
              hint="Subtask đi theo sprint của công việc cha; công việc cha tự chuyển Xong khi mọi subtask xong"
              className="sm:col-span-6"
            >
              {(id) => (
                <Select
                  id={id}
                  value={form.parent_id ?? ""}
                  onChange={(e) => chooseParent(e.target.value ? Number(e.target.value) : null)}
                >
                  <option value="">— Chọn công việc cha —</option>
                  {parentOptions.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.code} · {w.title}
                      {w.sprint_id ? ` (${sprintName.get(w.sprint_id) ?? "sprint"})` : " (Backlog)"}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}
          <Field label="Mô tả" hint={pasteHint("bug")} className="sm:col-span-6">
            {(id) => (
              <ImageTextEditor
                id={id}
                rows={4}
                value={form.description}
                onChange={(v) => set("description", v)}
                source={textSource("bug")}
                editable={canEdit}
              />
            )}
          </Field>
          <Field label="Tiêu chí hoàn thành" hint={pasteHint("result")} className="sm:col-span-6">
            {(id) => (
              <ImageTextEditor
                id={id}
                rows={2}
                value={form.acceptance_criteria}
                onChange={(v) => set("acceptance_criteria", v)}
                source={textSource("result")}
                editable={canEdit}
              />
            )}
          </Field>
          <Field
            label="Trạng thái"
            hint={hasSubtasks ? "Tự chuyển Xong khi mọi subtask xong" : undefined}
            className="sm:col-span-3"
          >
            {(id) => (
              <EnumSelect id={id} options={WORK_ITEM_STATUS} value={form.status} onChange={(v) => v && set("status", v)} />
            )}
          </Field>
          <Field label="Ưu tiên" className="sm:col-span-3">
            {(id) => <EnumSelect id={id} options={PRIORITY} value={form.priority} onChange={(v) => v && set("priority", v)} />}
          </Field>
          <Field
            label="Người thực hiện"
            hint={can("work_item.assign") ? "Giao cho một hoặc nhiều người" : "Bạn chỉ có thể tự nhận / tự gỡ mình"}
            className="sm:col-span-6"
          >
            {(id) => (
              <MultiMemberSelect
                id={id}
                pid={pid}
                value={form.assignee_ids}
                onChange={(v) => set("assignee_ids", v)}
                only={can("work_item.assign") ? undefined : me ? [me.id] : []}
                disabled={!canEdit}
              />
            )}
          </Field>
          <Field
            label="Sprint"
            hint={isSubtask ? "Subtask đi theo sprint của công việc cha" : undefined}
            className="sm:col-span-3"
          >
            {(id) => (
              <SprintSelect
                id={id}
                pid={pid}
                disabled={isSubtask}
                value={form.sprint_id}
                onChange={(v) =>
                  // Vào sprint: backlog -> todo; về backlog: todo -> backlog (giống backend)
                  setForm((f) => ({
                    ...f,
                    sprint_id: v,
                    status: v && f.status === "backlog" ? "todo" : !v && f.status === "todo" ? "backlog" : f.status,
                  }))
                }
              />
            )}
          </Field>
          <Field label="Yêu cầu khách hàng" className="sm:col-span-3">
            {(id) => (
              <Select
                id={id}
                value={form.requirement_id ?? ""}
                onChange={(e) => set("requirement_id", e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">— Không gắn —</option>
                {requirements.data?.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.code} · {r.title}
                  </option>
                ))}
                {item?.requirement_id && !requirements.data?.some((r) => r.id === item.requirement_id) && (
                  <option value={item.requirement_id}>Yêu cầu #{item.requirement_id}</option>
                )}
              </Select>
            )}
          </Field>
          <Field label="Story point" className="sm:col-span-1">
            {(id) => (
              <Input id={id} type="number" min={0} step={0.5} value={form.story_points} onChange={(e) => set("story_points", e.target.value)} />
            )}
          </Field>
          <Field label="Ước lượng (h)" className="sm:col-span-2">
            {(id) => (
              <Input
                id={id}
                type="number"
                min={0}
                step={0.5}
                value={form.original_estimate_hours}
                onChange={(e) => set("original_estimate_hours", e.target.value)}
              />
            )}
          </Field>
          <Field label="Còn lại (h)" className="sm:col-span-1">
            {(id) => (
              <Input
                id={id}
                type="number"
                min={0}
                step={0.5}
                value={form.remaining_hours}
                onChange={(e) => set("remaining_hours", e.target.value)}
              />
            )}
          </Field>
          <Field label="Hạn" className="sm:col-span-2">
            {(id) => <Input id={id} type="date" value={form.due_date} onChange={(e) => set("due_date", e.target.value)} />}
          </Field>
        </fieldset>

        {item && !item.parent_id && (
          <section className="mt-6">
            <h4 className="mb-2 text-[13px] font-semibold text-ink-2">Subtask</h4>
            <Subtasks pid={pid} parent={item} canEdit={canEdit} onOpen={setRelated} />
          </section>
        )}

        <WorkItemImages images={images} />

        <section className="mt-6">
          <h4 className="mb-2 text-[13px] font-semibold text-ink-2">File đính kèm</h4>
          <FileAttachments files={files} />
        </section>

        {editing && logs.data && (
          <section className="mt-6">
            <h4 className="mb-2 text-[13px] font-semibold text-ink-2">
              Log công việc · tổng {fmtHours(loggedTotal)}
            </h4>
            {logs.data.items.length === 0 ? (
              <p className="text-sm text-ink-3">Chưa có log.</p>
            ) : (
              <ul className="divide-y divide-line rounded-lg border border-line">
                {logs.data.items.map((l) => (
                  <li key={l.id} className="flex items-start gap-3 px-3 py-2 text-sm">
                    <span className="w-12 shrink-0 font-medium tabular-nums">{fmtHours(l.hours)}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start gap-1">
                        <ExpandableText className="flex-1" text={withoutImages(l.description)} />
                        <TextImagesButton pid={pid} text={l.description} />
                      </div>
                      <p className="text-xs text-ink-3">
                        {byId.get(l.user_id)?.full_name ?? `#${l.user_id}`} · {fmtDate(l.log_date)} ·{" "}
                        {ACTIVITY_TYPE[l.activity_type]}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </Modal>
      {logOpen && item && <WorkLogModal open pid={pid} workItem={item} onClose={() => setLogOpen(false)} />}
      {related && <WorkItemModal key={related.id} pid={pid} item={related} onClose={() => setRelated(null)} />}
    </>
  );
}
