"use client";

import { Select } from "@/components/ui/form";
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
