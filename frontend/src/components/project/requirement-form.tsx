"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ImageTextEditor } from "@/components/project/image-text-editor";
import { EnumSelect, MemberSelect } from "@/components/project/selects";
import { PASTE_HINT, useInlineImages } from "@/components/text-images";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useProjectPerms } from "@/lib/hooks";
import { PRIORITY, REQUIREMENT_SOURCE, REQUIREMENT_TYPE } from "@/lib/labels";
import type { Priority, Requirement, RequirementSource, RequirementType } from "@/lib/types";

type FormState = {
  title: string;
  description: string;
  acceptance_criteria: string;
  type: RequirementType;
  source: RequirementSource;
  priority: Priority;
  business_value: string;
  estimated_hours: string;
  expected_date: string;
  due_date: string;
  target_release: string;
  assignee_id: number | null;
  tags: string;
};

function initial(req?: Requirement): FormState {
  return {
    title: req?.title ?? "",
    description: req?.description ?? "",
    acceptance_criteria: req?.acceptance_criteria ?? "",
    type: req?.type ?? "feature",
    source: req?.source ?? "email",
    priority: req?.priority ?? "medium",
    business_value: req?.business_value?.toString() ?? "",
    estimated_hours: req?.estimated_hours != null ? String(req.estimated_hours) : "",
    expected_date: req?.expected_date ?? "",
    due_date: req?.due_date ?? "",
    target_release: req?.target_release ?? "",
    assignee_id: req?.assignee_id ?? null,
    tags: req?.tags.join(", ") ?? "",
  };
}

/** Modal tạo / sửa yêu cầu khách hàng. */
export function RequirementFormModal({
  pid,
  open,
  onClose,
  requirement,
  onSaved,
}: {
  pid: number;
  open: boolean;
  onClose: () => void;
  requirement?: Requirement;
  onSaved?: (r: Requirement) => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useProjectPerms(pid);
  const [form, setForm] = useState<FormState>(() => initial(requirement));
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));
  const editing = !!requirement;
  const canAssign = can("requirement.assign");
  const images = useInlineImages(pid, [form.description, form.acceptance_criteria]);

  const mutation = useMutation({
    mutationFn: async () => {
      const body = {
        title: form.title.trim(),
        description: form.description || null,
        acceptance_criteria: form.acceptance_criteria || null,
        type: form.type,
        source: form.source,
        priority: form.priority,
        business_value: form.business_value ? Number(form.business_value) : null,
        estimated_hours: form.estimated_hours ? Number(form.estimated_hours) : null,
        expected_date: form.expected_date || null,
        due_date: form.due_date || null,
        target_release: form.target_release || null,
        tags: form.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        ...(canAssign ? { assignee_id: form.assignee_id } : {}),
      };
      const res = editing
        ? await api.patch<Requirement>(`/projects/${pid}/requirements/${requirement.id}`, body)
        : await api.post<Requirement>(`/projects/${pid}/requirements`, body);
      return res.data;
    },
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: ["project", pid, "requirements"] });
      toast.success(editing ? "Đã cập nhật yêu cầu" : `Đã tạo yêu cầu ${saved.code}`);
      onSaved?.(saved);
      onClose();
    },
    onError: toast.error,
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={editing ? `Sửa yêu cầu ${requirement.code}` : "Yêu cầu khách hàng mới"}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button
            variant="primary"
            loading={mutation.isPending}
            disabled={!form.title.trim() || images.uploading > 0}
            onClick={() => mutation.mutate()}
          >
            {editing ? "Lưu thay đổi" : "Tạo yêu cầu"}
          </Button>
        </>
      }
    >
      <form
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!images.uploading) mutation.mutate();
        }}
      >
        <Field label="Tiêu đề" required className="sm:col-span-2">
          {(id) => (
            <Input id={id} autoFocus value={form.title} onChange={(e) => set("title", e.target.value)} maxLength={500} />
          )}
        </Field>
        <Field label="Mô tả" hint={PASTE_HINT} className="sm:col-span-2">
          {(id) => (
            <ImageTextEditor
              id={id}
              rows={4}
              value={form.description}
              onChange={(v) => set("description", v)}
              source={images.source}
            />
          )}
        </Field>
        <Field label="Tiêu chí nghiệm thu" hint={PASTE_HINT} className="sm:col-span-2">
          {(id) => (
            <ImageTextEditor
              id={id}
              rows={3}
              placeholder="Mỗi tiêu chí một dòng"
              value={form.acceptance_criteria}
              onChange={(v) => set("acceptance_criteria", v)}
              source={images.source}
            />
          )}
        </Field>
        <Field label="Loại">
          {(id) => <EnumSelect id={id} options={REQUIREMENT_TYPE} value={form.type} onChange={(v) => v && set("type", v)} />}
        </Field>
        <Field label="Mức ưu tiên">
          {(id) => <EnumSelect id={id} options={PRIORITY} value={form.priority} onChange={(v) => v && set("priority", v)} />}
        </Field>
        <Field label="Nguồn tiếp nhận">
          {(id) => (
            <EnumSelect id={id} options={REQUIREMENT_SOURCE} value={form.source} onChange={(v) => v && set("source", v)} />
          )}
        </Field>
        {canAssign && (
          <Field label="Người phụ trách">
            {(id) => <MemberSelect id={id} pid={pid} value={form.assignee_id} onChange={(v) => set("assignee_id", v)} />}
          </Field>
        )}
        <Field label="Ngày khách hàng mong muốn">
          {(id) => (
            <Input id={id} type="date" value={form.expected_date} onChange={(e) => set("expected_date", e.target.value)} />
          )}
        </Field>
        <Field label="Ngày cam kết">
          {(id) => <Input id={id} type="date" value={form.due_date} onChange={(e) => set("due_date", e.target.value)} />}
        </Field>
        <Field label="Giá trị kinh doanh" hint="1 – 100">
          {(id) => (
            <Input
              id={id}
              type="number"
              min={1}
              max={100}
              value={form.business_value}
              onChange={(e) => set("business_value", e.target.value)}
            />
          )}
        </Field>
        <Field label="Ước lượng (giờ)">
          {(id) => (
            <Input
              id={id}
              type="number"
              min={0}
              step="0.5"
              value={form.estimated_hours}
              onChange={(e) => set("estimated_hours", e.target.value)}
            />
          )}
        </Field>
        <Field label="Phiên bản phát hành">
          {(id) => (
            <Input id={id} value={form.target_release} onChange={(e) => set("target_release", e.target.value)} />
          )}
        </Field>
        <Field label="Tag" hint="Cách nhau bởi dấu phẩy">
          {(id) => <Input id={id} value={form.tags} onChange={(e) => set("tags", e.target.value)} />}
        </Field>
        <button type="submit" hidden />
      </form>
    </Modal>
  );
}
