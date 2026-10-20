"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserMinus, UserPlus } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { Checkbox, Field, Select } from "@/components/ui/form";
import { Avatar, Card, Empty, Spinner, Table } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMembers, useProjectId, useProjectPerms, useRoles } from "@/lib/hooks";
import type { Page, User } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

const ROLE_TONE: Record<string, "violet" | "indigo" | "teal" | "blue" | "amber" | "gray" | "orange"> = {
  PRODUCT_OWNER: "violet",
  SCRUM_MASTER: "indigo",
  BA: "teal",
  DEVELOPER: "blue",
  TESTER: "amber",
  CUSTOMER: "orange",
  VIEWER: "gray",
};

function AddMemberModal({ pid, existing, onClose }: { pid: number; existing: Set<number>; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const roles = useRoles();
  const [userId, setUserId] = useState<number | null>(null);
  const [roleIds, setRoleIds] = useState<number[]>([]);
  const users = useQuery({
    queryKey: ["users", "all"],
    queryFn: async () => (await api.get<Page<User>>("/users", { params: { size: 200, status: "active" } })).data.items,
  });
  const projectRoles = (roles.data ?? []).filter((r) => r.scope === "project");
  const add = useMutation({
    mutationFn: () => api.post(`/projects/${pid}/members`, { user_id: userId, role_ids: roleIds }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", pid, "members"] });
      toast.success("Đã thêm thành viên");
      onClose();
    },
    onError: toast.error,
  });

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title="Thêm thành viên"
      description="Thêm người mới, hoặc thêm vai trò cho thành viên hiện có"
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button variant="primary" loading={add.isPending} disabled={!userId || !roleIds.length} onClick={() => add.mutate()}>
            Thêm
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Người dùng" required>
          {(id) => (
            <Select id={id} value={userId ?? ""} onChange={(e) => setUserId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">— Chọn —</option>
              {users.data?.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name} ({u.username}){existing.has(u.id) ? " · đã là thành viên" : ""}
                  {u.customer_id ? " · khách hàng" : ""}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <fieldset>
          <legend className="mb-2 text-[13px] font-medium text-ink-2">Vai trò trong dự án</legend>
          <div className="grid gap-2">
            {projectRoles.map((r) => (
              <Checkbox
                key={r.id}
                label={
                  <span>
                    <span className="font-medium text-ink">{r.name}</span>
                    {r.description && <span className="text-ink-3"> — {r.description}</span>}
                  </span>
                }
                checked={roleIds.includes(r.id)}
                onChange={(e) =>
                  setRoleIds((ids) => (e.target.checked ? [...ids, r.id] : ids.filter((x) => x !== r.id)))
                }
              />
            ))}
          </div>
        </fieldset>
      </div>
    </Modal>
  );
}

export default function MembersPage() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const toast = useToast();
  const { me } = useAuth();
  const { can } = useProjectPerms(pid);
  const { members, isPending } = useMembers(pid);
  const [adding, setAdding] = useState(false);
  const canManage = can("project.member.manage");

  const remove = useMutation({
    mutationFn: ({ userId, roleId }: { userId: number; roleId?: number }) =>
      api.delete(`/projects/${pid}/members/${userId}`, { params: roleId ? { role_id: roleId } : {} }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", pid, "members"] });
      toast.success("Đã cập nhật thành viên");
    },
    onError: toast.error,
  });

  return (
    <Card>
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h3 className="text-sm font-semibold">{members.length} thành viên</h3>
        {canManage && (
          <Button size="sm" variant="primary" icon={<UserPlus className="size-4" />} onClick={() => setAdding(true)}>
            Thêm thành viên
          </Button>
        )}
      </div>
      {isPending ? (
        <Spinner />
      ) : !members.length ? (
        <Empty title="Chưa có thành viên" />
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Thành viên</th>
              <th>Vai trò</th>
              <th>Tham gia</th>
              <th className="w-12" />
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user.id}>
                <td>
                  <span className="flex items-center gap-2.5">
                    <Avatar id={m.user.id} name={m.user.full_name} />
                    <span>
                      <span className="block font-medium">
                        {m.user.full_name}
                        {m.user.id === me?.id && <span className="ml-1.5 text-xs text-ink-3">(bạn)</span>}
                      </span>
                      <span className="text-xs text-ink-3">@{m.user.username}</span>
                    </span>
                  </span>
                </td>
                <td>
                  <div className="flex flex-wrap gap-1">
                    {m.roles.map((r) => (
                      <Badge key={r.id} tone={ROLE_TONE[r.code] ?? "gray"}>
                        {r.name}
                        {canManage && m.roles.length > 1 && (
                          <button
                            type="button"
                            aria-label={`Bỏ vai trò ${r.name}`}
                            className="-mr-1 ml-0.5 rounded px-0.5 hover:bg-black/10"
                            onClick={() => remove.mutate({ userId: m.user.id, roleId: r.id })}
                          >
                            ×
                          </button>
                        )}
                      </Badge>
                    ))}
                  </div>
                </td>
                <td className="tabular-nums text-ink-2">{fmtDate(m.joined_at)}</td>
                <td className="text-right">
                  {canManage && m.user.id !== me?.id && (
                    <IconButton
                      label="Xoá khỏi dự án"
                      className="hover:bg-danger-soft hover:text-danger"
                      onClick={() => confirm(`Xoá ${m.user.full_name} khỏi dự án?`) && remove.mutate({ userId: m.user.id })}
                    >
                      <UserMinus className="size-4" />
                    </IconButton>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {adding && (
        <AddMemberModal pid={pid} existing={new Set(members.map((m) => m.user.id))} onClose={() => setAdding(false)} />
      )}
    </Card>
  );
}
