"use client";

import { X } from "lucide-react";

import { Select } from "@/components/ui/form";
import { Avatar } from "@/components/ui/misc";
import { useMembers, useSprints } from "@/lib/hooks";
import { SPRINT_STATUS } from "@/lib/labels";

type SelectProps = Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange">;

/** Chọn thành viên dự án; value = user id hoặc null. */
export function MemberSelect({
  pid,
  value,
  onChange,
  emptyLabel = "— Chưa giao —",
  ...rest
}: SelectProps & {
  pid: number;
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  emptyLabel?: string;
}) {
  const { members } = useMembers(pid);
  return (
    <Select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)} {...rest}>
      <option value="">{emptyLabel}</option>
      {members.map((m) => (
        <option key={m.user.id} value={m.user.id}>
          {m.user.full_name}
        </option>
      ))}
    </Select>
  );
}

/**
 * Chọn nhiều thành viên dự án (người phụ trách công việc); value = danh sách user id.
 * `only`: chỉ được thêm / gỡ những người này (vd: không có quyền giao việc thì chỉ tự nhận / tự gỡ mình).
 */
export function MultiMemberSelect({
  pid,
  value,
  onChange,
  only,
  id,
  disabled,
}: {
  pid: number;
  value: number[];
  onChange: (v: number[]) => void;
  only?: number[];
  id?: string;
  disabled?: boolean;
}) {
  const { members, byId } = useMembers(pid);
  const editable = (uid: number) => !disabled && (!only || only.includes(uid));
  const addable = members.filter((m) => !value.includes(m.user.id) && editable(m.user.id));
  return (
    <div className="flex min-h-9 flex-wrap items-center gap-1.5">
      {value.map((uid) => {
        const name = byId.get(uid)?.full_name ?? `#${uid}`;
        return (
          <span key={uid} className="inline-flex items-center gap-1 rounded-full bg-subtle py-0.5 pr-1 pl-0.5 text-[13px]">
            <Avatar size="sm" id={uid} name={name} />
            <span className="max-w-36 truncate">{name}</span>
            {editable(uid) && (
              <button
                type="button"
                aria-label={`Gỡ ${name}`}
                onClick={() => onChange(value.filter((v) => v !== uid))}
                className="rounded-full p-0.5 text-ink-3 hover:bg-danger-soft hover:text-danger"
              >
                <X className="size-3" />
              </button>
            )}
          </span>
        );
      })}
      {addable.length > 0 && (
        <Select
          id={id}
          aria-label="Thêm người phụ trách"
          className="h-8 w-auto min-w-36 text-[13px]"
          value=""
          onChange={(e) => e.target.value && onChange([...value, Number(e.target.value)])}
        >
          <option value="">{value.length ? "+ Thêm người…" : "— Chưa giao —"}</option>
          {addable.map((m) => (
            <option key={m.user.id} value={m.user.id}>
              {m.user.full_name}
            </option>
          ))}
        </Select>
      )}
      {!value.length && !addable.length && <span className="text-sm text-ink-3">Chưa giao</span>}
    </div>
  );
}

/** Chọn sprint chưa kết thúc; value null = Product Backlog. */
export function SprintSelect({
  pid,
  value,
  onChange,
  ...rest
}: SelectProps & { pid: number; value: number | null | undefined; onChange: (v: number | null) => void }) {
  const { data: sprints = [] } = useSprints(pid);
  const open = sprints.filter((s) => s.status === "planned" || s.status === "active" || s.id === value);
  return (
    <Select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)} {...rest}>
      <option value="">Product Backlog</option>
      {open.map((s) => (
        <option key={s.id} value={s.id}>
          {s.name} ({SPRINT_STATUS[s.status].label})
        </option>
      ))}
    </Select>
  );
}

/** Select từ một map nhãn { value: label }. */
export function EnumSelect<T extends string>({
  options,
  value,
  onChange,
  emptyLabel,
  ...rest
}: SelectProps & {
  options: Record<T, string | { label: string }>;
  value: T | "" | undefined;
  onChange: (v: T | "") => void;
  emptyLabel?: string;
}) {
  return (
    <Select value={value ?? ""} onChange={(e) => onChange(e.target.value as T | "")} {...rest}>
      {emptyLabel !== undefined && <option value="">{emptyLabel}</option>}
      {(Object.entries(options) as [T, string | { label: string }][]).map(([key, meta]) => (
        <option key={key} value={key}>
          {typeof meta === "string" ? meta : meta.label}
        </option>
      ))}
    </Select>
  );
}
