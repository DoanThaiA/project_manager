"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { EnumSelect } from "@/components/project/selects";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMembers } from "@/lib/hooks";
import { PROJECT_STATUS } from "@/lib/labels";
import type { Customer, Page, Project, ProjectStatus, User } from "@/lib/types";
import { num } from "@/lib/utils";

/** Tạo dự án mới hoặc sửa thông tin dự án. Render có điều kiện. */
export function ProjectFormModal({ project, onClose }: { project?: Project; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const router = useRouter();
  const { can, me } = useAuth();
  const editing = !!project;
  const [deleting, setDeleting] = useState(false);
  const members = useMembers(project?.id ?? 0);

  const [form, setForm] = useState({
    key: project?.key ?? "",
    name: project?.name ?? "",
    description: project?.description ?? "",
    customer_id: project?.customer_id ?? null,
    product_owner_id: project?.product_owner_id ?? null,
    scrum_master_id: project?.scrum_master_id ?? null,
    status: project?.status ?? ("planning" as ProjectStatus),
    start_date: project?.start_date ?? "",
    end_date: project?.end_date ?? "",
    sprint_duration_days: project?.sprint_duration_days ?? 14,
    budget_hours: project?.budget_hours != null ? String(num(project.budget_hours)) : "",
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));

  const customers = useQuery({
    queryKey: ["customers", "all"],
    queryFn: async () => (await api.get<Page<Customer>>("/customers", { params: { size: 200 } })).data.items,
    enabled: can("customer.view"),
  });
  // Ứng viên PO / SM: khi tạo mới lấy danh sách user (cần user.view), khi sửa lấy thành viên dự án
  const users = useQuery({
    queryKey: ["users", "all"],
    queryFn: async () => (await api.get<Page<User>>("/users", { params: { size: 200, status: "active" } })).data.items,
    enabled: !editing && can("user.view"),
  });
  const people = editing
    ? members.members.map((m) => ({ id: m.user.id, name: m.user.full_name }))
    : (users.data ?? []).filter((u) => !u.customer_id).map((u) => ({ id: u.id, name: u.full_name }));

  const mutation = useMutation({
    mutationFn: async () => {
      const body = {
        name: form.name.trim(),
        description: form.description || null,
        customer_id: form.customer_id,
        product_owner_id: form.product_owner_id,
        scrum_master_id: form.scrum_master_id,
        status: form.status,
        start_date: form.start_date || null,
        end_date: form.end_date || null,
        sprint_duration_days: Number(form.sprint_duration_days),
        budget_hours: form.budget_hours ? Number(form.budget_hours) : null,
      };
      return editing
        ? (await api.patch<Project>(`/projects/${project.id}`, body)).data
        : (await api.post<Project>("/projects", { ...body, key: form.key.toUpperCase() })).data;
    },
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["project", saved.id] });
      toast.success(editing ? "Đã lưu dự án" : `Đã tạo dự án ${saved.key}`);
      onClose();
      if (!editing) router.push(`/projects/${saved.id}`);
    },
    onError: toast.error,
  });

  const personSelect = (id: string, value: number | null, onChange: (v: number | null) => void, empty: string) => (
    <Select id={id} value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">{empty}</option>
      {people.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </Select>
  );

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={editing ? `Sửa dự án ${project.key}` : "Dự án mới"}
      footer={
        <>
          {editing && me?.is_system_admin && (
            <Button
              variant="ghost"
              className="mr-auto text-danger hover:bg-danger-soft hover:text-danger"
              icon={<Trash2 className="size-4" />}
              onClick={() => setDeleting(true)}
            >
              Xoá dự án
            </Button>
          )}
          <Button onClick={onClose}>Huỷ</Button>
          <Button
            variant="primary"
            loading={mutation.isPending}
            disabled={!form.name.trim() || (!editing && !/^[A-Z][A-Z0-9]{1,9}$/.test(form.key.toUpperCase()))}
            onClick={() => mutation.mutate()}
          >
            {editing ? "Lưu" : "Tạo dự án"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-4">
        <Field label="Mã dự án" required hint="2–10 ký tự, vd: ERP" className="sm:col-span-1">
          {(id) => (
            <Input
              id={id}
              value={form.key}
              disabled={editing}
              maxLength={10}
              autoFocus={!editing}
              className="uppercase"
              onChange={(e) => set("key", e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
            />
          )}
        </Field>
        <Field label="Tên dự án" required className="sm:col-span-3">
          {(id) => <Input id={id} value={form.name} onChange={(e) => set("name", e.target.value)} />}
        </Field>
        <Field label="Mô tả" className="sm:col-span-4">
          {(id) => <Textarea id={id} value={form.description} onChange={(e) => set("description", e.target.value)} />}
        </Field>
        {can("customer.view") && (
          <Field label="Khách hàng" className="sm:col-span-2">
            {(id) => (
              <Select
                id={id}
                value={form.customer_id ?? ""}
                onChange={(e) => set("customer_id", e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">— Nội bộ —</option>
                {customers.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.code} · {c.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
        <Field label="Trạng thái" className="sm:col-span-2">
          {(id) => <EnumSelect id={id} options={PROJECT_STATUS} value={form.status} onChange={(v) => v && set("status", v)} />}
        </Field>
        {people.length > 0 && (
          <>
            <Field label="Product Owner" hint={editing ? undefined : "Mặc định: bạn"} className="sm:col-span-2">
              {(id) => personSelect(id, form.product_owner_id, (v) => set("product_owner_id", v), "— Mặc định —")}
            </Field>
            <Field label="Scrum Master" className="sm:col-span-2">
              {(id) => personSelect(id, form.scrum_master_id, (v) => set("scrum_master_id", v), "— Chưa chọn —")}
            </Field>
          </>
        )}
        <Field label="Ngày bắt đầu" className="sm:col-span-1">
          {(id) => <Input id={id} type="date" value={form.start_date} onChange={(e) => set("start_date", e.target.value)} />}
        </Field>
        <Field label="Ngày kết thúc" className="sm:col-span-1">
          {(id) => <Input id={id} type="date" value={form.end_date} onChange={(e) => set("end_date", e.target.value)} />}
        </Field>
        <Field label="Độ dài sprint (ngày)" className="sm:col-span-1">
          {(id) => (
            <Input
              id={id}
              type="number"
              min={1}
              max={60}
              value={form.sprint_duration_days}
              onChange={(e) => set("sprint_duration_days", Number(e.target.value))}
            />
          )}
        </Field>
        <Field label="Ngân sách (giờ)" className="sm:col-span-1">
          {(id) => (
            <Input id={id} type="number" min={0} value={form.budget_hours} onChange={(e) => set("budget_hours", e.target.value)} />
          )}
        </Field>
      </div>
      {deleting && project && (
        <DeleteProjectModal
          project={project}
          onClose={() => setDeleting(false)}
          onDeleted={() => {
            onClose();
            router.push("/projects");
          }}
        />
      )}
    </Modal>
  );
}

/** Xác nhận xoá dự án (chỉ quản trị hệ thống): phải gõ đúng mã dự án. */
function DeleteProjectModal({
  project,
  onClose,
  onDeleted,
}: {
  project: Project;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [typed, setTyped] = useState("");

  const remove = useMutation({
    mutationFn: () => api.delete(`/projects/${project.id}`),
    onSuccess: () => {
      qc.removeQueries({ queryKey: ["project", project.id] });
      qc.invalidateQueries({ queryKey: ["projects"] });
      toast.success(`Đã xoá dự án ${project.key}`);
      onDeleted();
    },
    onError: toast.error,
  });

  return (
    <Modal
      open
      size="sm"
      onClose={onClose}
      title={`Xoá dự án ${project.key}?`}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button
            variant="danger"
            icon={<Trash2 className="size-4" />}
            loading={remove.isPending}
            disabled={typed.trim().toUpperCase() !== project.key}
            onClick={() => remove.mutate()}
          >
            Xoá dự án
          </Button>
        </>
      }
    >
      <p className="text-sm text-ink-2">
        Dự án <strong>{project.name}</strong> cùng toàn bộ yêu cầu, backlog, sprint, log công việc sẽ bị ẩn khỏi hệ
        thống với mọi người dùng. Dữ liệu vẫn được giữ trong database (xoá mềm) và nhật ký hoạt động.
      </p>
      <Field label={`Gõ mã dự án "${project.key}" để xác nhận`} className="mt-4">
        {(id) => <Input id={id} autoFocus autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />}
      </Field>
    </Modal>
  );
}
