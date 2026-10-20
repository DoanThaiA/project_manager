"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Save } from "lucide-react";
import { Fragment, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Card, PageHeader, Spinner } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useRoles } from "@/lib/hooks";
import type { Permission, RoleDetail } from "@/lib/types";
import { cn } from "@/lib/utils";

const MODULE_LABEL: Record<string, string> = {
  user: "Người dùng",
  role: "Vai trò",
  customer: "Khách hàng",
  project: "Dự án",
  sprint: "Sprint",
  requirement: "Yêu cầu khách hàng",
  work_item: "Công việc",
  work_log: "Log công việc",
  activity_log: "Nhật ký",
  report: "Báo cáo",
};

function CreateRoleModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({ code: "", name: "", scope: "project", description: "" });
  const create = useMutation({
    mutationFn: () => api.post("/roles", { ...form, description: form.description || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["roles"] });
      toast.success("Đã tạo vai trò");
      onClose();
    },
    onError: toast.error,
  });
  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title="Vai trò mới"
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button
            variant="primary"
            loading={create.isPending}
            disabled={!/^[A-Z][A-Z0-9_]{1,49}$/.test(form.code) || !form.name}
            onClick={() => create.mutate()}
          >
            Tạo
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Mã" required hint="Chữ in hoa, vd: TECH_LEAD">
          {(id) => (
            <Input
              id={id}
              value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "") })}
            />
          )}
        </Field>
        <Field label="Tên" required>
          {(id) => <Input id={id} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />}
        </Field>
        <Field label="Phạm vi">
          {(id) => (
            <Select id={id} value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}>
              <option value="project">Trong dự án</option>
              <option value="system">Toàn hệ thống</option>
            </Select>
          )}
        </Field>
        <Field label="Mô tả">
          {(id) => <Input id={id} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />}
        </Field>
      </div>
    </Modal>
  );
}

export default function RolesPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const roles = useRoles();
  const [creating, setCreating] = useState(false);
  // Thay đổi chưa lưu: roleId -> tập permission id
  const [draft, setDraft] = useState<Record<number, Set<number>>>({});

  const permissions = useQuery({
    queryKey: ["permissions"],
    queryFn: async () => (await api.get<Permission[]>("/permissions")).data,
  });
  const details = useQueries({
    queries: (roles.data ?? []).map((r) => ({
      queryKey: ["roles", r.id],
      queryFn: async () => (await api.get<RoleDetail>(`/roles/${r.id}`)).data,
    })),
  });
  const saved = useMemo(() => {
    const map: Record<number, Set<number>> = {};
    for (const d of details) if (d.data) map[d.data.id] = new Set(d.data.permissions.map((p) => p.id));
    return map;
  }, [details]);

  const save = useMutation({
    mutationFn: async () => {
      for (const [roleId, perms] of Object.entries(draft)) {
        await api.put(`/roles/${roleId}/permissions`, { permission_ids: [...perms] });
      }
    },
    onSuccess: () => {
      setDraft({});
      qc.invalidateQueries({ queryKey: ["roles"] });
      toast.success("Đã lưu phân quyền");
    },
    onError: toast.error,
  });

  if (roles.isPending || permissions.isPending || details.some((d) => d.isPending)) return <Spinner />;

  // Vai trò hệ thống trước, sau đó vai trò dự án
  const ordered = [...(roles.data ?? [])].sort((a, b) => b.scope.localeCompare(a.scope) || a.id - b.id);
  const modules = Object.groupBy(permissions.data ?? [], (p) => p.module);
  const current = (roleId: number) => draft[roleId] ?? saved[roleId] ?? new Set<number>();
  const toggle = (roleId: number, permId: number) =>
    setDraft((d) => {
      const next = new Set(current(roleId));
      if (next.has(permId)) next.delete(permId);
      else next.add(permId);
      return { ...d, [roleId]: next };
    });
  const dirty = Object.keys(draft).length > 0;

  return (
    <>
      <PageHeader
        title="Vai trò & quyền"
        description="Ma trận chức năng cho từng vai trò. Vai trò dự án áp dụng trong từng dự án mà người dùng tham gia."
        actions={
          <>
            <Button icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
              Vai trò mới
            </Button>
            <Button
              variant="primary"
              icon={<Save className="size-4" />}
              disabled={!dirty}
              loading={save.isPending}
              onClick={() => save.mutate()}
            >
              Lưu thay đổi
            </Button>
          </>
        }
      />
      <Card className="overflow-hidden">
        <div className="max-h-[calc(100dvh-220px)] overflow-auto">
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr className="border-b border-line">
                <th className="sticky left-0 z-20 min-w-64 bg-surface px-4 py-2 text-left text-xs font-medium text-ink-3">
                  Chức năng
                </th>
                {ordered.map((r) => (
                  <th key={r.id} className="min-w-24 px-2 py-2 text-center align-bottom">
                    <span className="block text-xs font-semibold">{r.name}</span>
                    <Badge className="mt-1" tone={r.scope === "system" ? "violet" : "blue"}>
                      {r.scope === "system" ? "Hệ thống" : "Dự án"}
                    </Badge>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(modules).map(([module, perms]) => (
                <Fragment key={module}>
                  <tr className="bg-subtle">
                    <td
                      colSpan={ordered.length + 1}
                      className="sticky left-0 px-4 py-1.5 text-xs font-semibold tracking-wide text-ink-2 uppercase"
                    >
                      {MODULE_LABEL[module] ?? module}
                    </td>
                  </tr>
                  {perms?.map((p) => (
                    <tr key={p.id} className="border-b border-line hover:bg-subtle/40">
                      <td className="sticky left-0 bg-surface px-4 py-1.5">
                        <span className="block">{p.name}</span>
                        <code className="text-[11px] text-ink-3">{p.code}</code>
                      </td>
                      {ordered.map((r) => {
                        const locked = r.code === "SYSTEM_ADMIN";
                        const checked = locked || current(r.id).has(p.id);
                        const changed = draft[r.id] && draft[r.id].has(p.id) !== (saved[r.id]?.has(p.id) ?? false);
                        return (
                          <td key={r.id} className={cn("text-center", changed && "bg-amber-50")}>
                            <input
                              type="checkbox"
                              aria-label={`${r.name}: ${p.name}`}
                              className="size-4 accent-brand disabled:opacity-50"
                              checked={checked}
                              disabled={locked}
                              onChange={() => toggle(r.id, p.id)}
                            />
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {creating && <CreateRoleModal onClose={() => setCreating(false)} />}
    </>
  );
}
