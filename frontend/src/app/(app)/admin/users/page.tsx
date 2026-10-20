"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Lock, LockOpen, Pencil, Plus, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";

import { Badge, MetaBadge } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { Checkbox, Field, Input, Select } from "@/components/ui/form";
import { Avatar, Card, Empty, PageHeader, Pagination, Spinner, Table } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api, clean } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useRoles } from "@/lib/hooks";
import type { Customer, Page, User, UserDetail } from "@/lib/types";
import { fmtRelative } from "@/lib/utils";

const STATUS = {
  active: { label: "Hoạt động", tone: "green" as const },
  inactive: { label: "Ngừng", tone: "gray" as const },
  locked: { label: "Đã khoá", tone: "red" as const },
};

function UserModal({ userId, onClose }: { userId?: number; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { me, can } = useAuth();
  const roles = useRoles();
  const editing = userId !== undefined;
  const detail = useQuery({
    queryKey: ["users", userId],
    queryFn: async () => (await api.get<UserDetail>(`/users/${userId}`)).data,
    enabled: editing,
  });
  const customers = useQuery({
    queryKey: ["customers", "all"],
    queryFn: async () => (await api.get<Page<Customer>>("/customers", { params: { size: 200 } })).data.items,
    enabled: can("customer.view"),
  });

  if (editing && detail.isPending) return null;
  return (
    <UserForm
      user={detail.data}
      systemRoles={(roles.data ?? []).filter((r) => r.scope === "system")}
      customers={customers.data ?? []}
      canSetAdmin={!!me?.is_system_admin}
      canSetRoles={can("role.manage") || !editing}
      onClose={onClose}
      onSaved={() => {
        qc.invalidateQueries({ queryKey: ["users"] });
        toast.success(editing ? "Đã lưu người dùng" : "Đã tạo người dùng");
        onClose();
      }}
      onError={toast.error}
    />
  );
}

function UserForm({
  user,
  systemRoles,
  customers,
  canSetAdmin,
  canSetRoles,
  onClose,
  onSaved,
  onError,
}: {
  user?: UserDetail;
  systemRoles: { id: number; name: string; description?: string | null }[];
  customers: Customer[];
  canSetAdmin: boolean;
  canSetRoles: boolean;
  onClose: () => void;
  onSaved: () => void;
  onError: (e: unknown) => void;
}) {
  const editing = !!user;
  const [form, setForm] = useState({
    username: user?.username ?? "",
    email: user?.email ?? "",
    password: "",
    full_name: user?.full_name ?? "",
    phone: user?.phone ?? "",
    job_title: user?.job_title ?? "",
    customer_id: user?.customer_id ?? null,
    is_system_admin: user?.is_system_admin ?? false,
    role_ids: user?.roles.map((r) => r.id) ?? [],
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));

  const save = useMutation({
    mutationFn: async () => {
      const profile = {
        email: form.email,
        full_name: form.full_name,
        phone: form.phone || null,
        job_title: form.job_title || null,
        customer_id: form.customer_id,
        ...(canSetAdmin ? { is_system_admin: form.is_system_admin } : {}),
      };
      if (!editing) {
        return api.post("/users", { ...profile, username: form.username, password: form.password, role_ids: form.role_ids });
      }
      await api.patch(`/users/${user.id}`, profile);
      if (canSetRoles) await api.put(`/users/${user.id}/roles`, { role_ids: form.role_ids });
    },
    onSuccess: onSaved,
    onError,
  });

  const valid =
    form.email && form.full_name && (editing || (/^[a-zA-Z0-9._-]{3,50}$/.test(form.username) && form.password.length >= 8));

  return (
    <Modal
      open
      onClose={onClose}
      title={editing ? `Sửa ${user.full_name}` : "Người dùng mới"}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button variant="primary" loading={save.isPending} disabled={!valid} onClick={() => save.mutate()}>
            Lưu
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Tên đăng nhập" required={!editing}>
          {(id) => (
            <Input id={id} value={form.username} disabled={editing} onChange={(e) => set("username", e.target.value)} />
          )}
        </Field>
        <Field label="Email" required>
          {(id) => <Input id={id} type="email" value={form.email} onChange={(e) => set("email", e.target.value)} />}
        </Field>
        <Field label="Họ tên" required>
          {(id) => <Input id={id} value={form.full_name} onChange={(e) => set("full_name", e.target.value)} />}
        </Field>
        {!editing && (
          <Field label="Mật khẩu" required hint="Tối thiểu 8 ký tự">
            {(id) => (
              <Input
                id={id}
                type="password"
                autoComplete="new-password"
                value={form.password}
                onChange={(e) => set("password", e.target.value)}
              />
            )}
          </Field>
        )}
        <Field label="Chức danh">
          {(id) => <Input id={id} value={form.job_title} onChange={(e) => set("job_title", e.target.value)} />}
        </Field>
        <Field label="Điện thoại">
          {(id) => <Input id={id} value={form.phone} onChange={(e) => set("phone", e.target.value)} />}
        </Field>
        {customers.length > 0 && (
          <Field label="Tài khoản của khách hàng" hint="Để trống nếu là nhân viên nội bộ" className="sm:col-span-2">
            {(id) => (
              <Select
                id={id}
                value={form.customer_id ?? ""}
                onChange={(e) => set("customer_id", e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">— Nội bộ —</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.code} · {c.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
        {canSetRoles && (
          <fieldset className="sm:col-span-2">
            <legend className="mb-2 text-[13px] font-medium text-ink-2">Vai trò hệ thống</legend>
            <div className="grid gap-2">
              {systemRoles
                .filter((r) => r.id && r.name)
                .map((r) => (
                  <Checkbox
                    key={r.id}
                    label={
                      <span>
                        <span className="font-medium text-ink">{r.name}</span>
                        {r.description && <span className="text-ink-3"> — {r.description}</span>}
                      </span>
                    }
                    checked={form.role_ids.includes(r.id)}
                    onChange={(e) =>
                      set("role_ids", e.target.checked ? [...form.role_ids, r.id] : form.role_ids.filter((x) => x !== r.id))
                    }
                  />
                ))}
            </div>
          </fieldset>
        )}
        {canSetAdmin && (
          <Checkbox
            className="sm:col-span-2"
            label="Quản trị hệ thống (toàn quyền)"
            checked={form.is_system_admin}
            onChange={(e) => set("is_system_admin", e.target.checked)}
          />
        )}
      </div>
    </Modal>
  );
}

export default function UsersPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { me, can } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState<{ userId?: number } | null>(null);
  const params = clean({ q: useDeferredValue(q), status, page, size: 25 });
  const users = useQuery({
    queryKey: ["users", "list", params],
    queryFn: async () => (await api.get<Page<User>>("/users", { params })).data,
    placeholderData: keepPreviousData,
  });

  const action = useMutation({
    mutationFn: async ({ user, kind }: { user: User; kind: "lock" | "unlock" | "reset" }) => {
      if (kind === "reset") {
        const pw = prompt(`Mật khẩu mới cho ${user.username} (tối thiểu 8 ký tự):`);
        if (!pw) return null;
        await api.post(`/users/${user.id}/reset-password`, { new_password: pw });
        return "Đã đặt lại mật khẩu";
      }
      await api.post(`/users/${user.id}/${kind}`);
      return kind === "lock" ? `Đã khoá ${user.username}` : `Đã mở khoá ${user.username}`;
    },
    onSuccess: (msg) => {
      if (!msg) return;
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(msg);
    },
    onError: toast.error,
  });

  return (
    <>
      <PageHeader
        title="Người dùng"
        actions={
          can("user.create") && (
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setModal({})}>
              Người dùng mới
            </Button>
          )
        }
      />
      <Card>
        <div className="flex flex-wrap gap-2 border-b border-line p-3">
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-3" />
            <Input
              aria-label="Tìm người dùng"
              placeholder="Tìm tên, username, email…"
              className="pl-8"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <Select
            aria-label="Trạng thái"
            className="w-40"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          >
            <option value="">Mọi trạng thái</option>
            {Object.entries(STATUS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </Select>
        </div>
        {users.isPending ? (
          <Spinner />
        ) : !users.data?.items.length ? (
          <Empty title="Không có người dùng" />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Người dùng</th>
                <th>Email</th>
                <th>Loại</th>
                <th>Trạng thái</th>
                <th>Đăng nhập gần nhất</th>
                <th className="w-32" />
              </tr>
            </thead>
            <tbody>
              {users.data.items.map((u) => (
                <tr key={u.id}>
                  <td>
                    <span className="flex items-center gap-2.5">
                      <Avatar id={u.id} name={u.full_name} />
                      <span>
                        <span className="block font-medium">{u.full_name}</span>
                        <span className="text-xs text-ink-3">
                          @{u.username}
                          {u.job_title && ` · ${u.job_title}`}
                        </span>
                      </span>
                    </span>
                  </td>
                  <td className="text-ink-2">{u.email}</td>
                  <td>
                    {u.is_system_admin ? (
                      <Badge tone="violet">Admin</Badge>
                    ) : u.customer_id ? (
                      <Badge tone="orange">Khách hàng</Badge>
                    ) : (
                      <Badge>Nội bộ</Badge>
                    )}
                  </td>
                  <td>
                    <MetaBadge meta={STATUS[u.status]} />
                  </td>
                  <td className="text-ink-3">{fmtRelative(u.last_login_at)}</td>
                  <td className="text-right whitespace-nowrap">
                    {can("user.update") && (
                      <>
                        <IconButton label="Sửa" onClick={() => setModal({ userId: u.id })}>
                          <Pencil className="size-3.5" />
                        </IconButton>
                        <IconButton label="Đặt lại mật khẩu" onClick={() => action.mutate({ user: u, kind: "reset" })}>
                          <KeyRound className="size-3.5" />
                        </IconButton>
                      </>
                    )}
                    {can("user.lock") &&
                      u.id !== me?.id &&
                      (u.status === "locked" ? (
                        <IconButton label="Mở khoá" onClick={() => action.mutate({ user: u, kind: "unlock" })}>
                          <LockOpen className="size-3.5" />
                        </IconButton>
                      ) : (
                        <IconButton
                          label="Khoá tài khoản"
                          className="hover:bg-danger-soft hover:text-danger"
                          onClick={() => confirm(`Khoá tài khoản ${u.username}?`) && action.mutate({ user: u, kind: "lock" })}
                        >
                          <Lock className="size-3.5" />
                        </IconButton>
                      ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {users.data && <Pagination page={page} size={users.data.size} total={users.data.total} onChange={setPage} />}
      </Card>
      {modal && <UserModal userId={modal.userId} onClose={() => setModal(null)} />}
    </>
  );
}
