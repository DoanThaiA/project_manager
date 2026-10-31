import { MetaBadge } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/misc";
import {
  type Tone,
  ACTION_LABEL,
  CRM_STATUS,
  ENTITY_LABEL,
  FIELD_LABEL,
  PROJECT_STATUS,
  REQUIREMENT_STATUS,
  SPRINT_STATUS,
  WORK_ITEM_STATUS,
  labelOf,
} from "@/lib/labels";
import type { ActivityLog } from "@/lib/types";
import { fmtDateTime, fmtRelative } from "@/lib/utils";

const HIDDEN_FIELDS = new Set(["id", "project_id", "created_at", "seq_no", "code", "tags"]);

const STATUS_META: Record<string, Record<string, { label: string; tone: Tone }>> = {
  requirements: REQUIREMENT_STATUS,
  work_items: WORK_ITEM_STATUS,
  sprints: SPRINT_STATUS,
  projects: PROJECT_STATUS,
  crm_contacts: CRM_STATUS,
};

/** Đổi id sang tên hiển thị (người dùng, sprint, vai trò…); trả undefined nếu không biết. */
export type ActivityResolver = (field: string, value: unknown) => string | undefined;

function renderValue(entity: string, field: string, value: unknown, resolve?: ActivityResolver) {
  if (value === null || value === undefined || value === "") return <span className="text-ink-3">trống</span>;
  if (field === "status" && typeof value === "string") {
    const meta = STATUS_META[entity]?.[value];
    if (meta) return <MetaBadge meta={meta} />;
  }
  const resolved = resolve?.(field, value);
  if (resolved) return resolved;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) return fmtDateTime(value);
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  return <span className="break-words">{text.length > 120 ? `${text.slice(0, 120)}…` : text}</span>;
}

function Changes({ log, resolve }: { log: ActivityLog; resolve?: ActivityResolver }) {
  const values = (log.action === "create" ? log.new_values : log.new_values ?? log.old_values) ?? {};
  const fields = Object.keys(values).filter((f) => !HIDDEN_FIELDS.has(f));
  if (log.action === "create" || log.action.endsWith("delete") || fields.length === 0) return null;
  if (log.entity_type === "project_members") {
    const roleId = (log.new_values ?? log.old_values)?.role_id;
    const role = resolve?.("role_id", roleId);
    return role ? <p className="mt-1 text-[13px] text-ink-3">Vai trò: {role}</p> : null;
  }
  return (
    <dl className="mt-1.5 space-y-1 text-[13px]">
      {fields.slice(0, 6).map((f) => (
        <div key={f} className="flex flex-wrap items-center gap-1.5">
          <dt className="text-ink-3">{labelOf(FIELD_LABEL, f)}:</dt>
          <dd className="flex flex-wrap items-center gap-1.5">
            {log.old_values && f in log.old_values && (
              <>
                <span className="text-ink-3 line-through decoration-ink-3/50">
                  {renderValue(log.entity_type, f, log.old_values[f], resolve)}
                </span>
                <span className="text-ink-3">→</span>
              </>
            )}
            {renderValue(log.entity_type, f, log.new_values?.[f], resolve)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function subject(log: ActivityLog, resolve?: ActivityResolver) {
  if (log.entity_type === "project_members" || log.entity_type === "users") {
    const name = resolve?.("user_id", log.entity_id);
    if (name) return name;
  }
  const v = (log.new_values ?? log.old_values ?? {}) as Record<string, unknown>;
  const name = v.code ?? v.title ?? v.name ?? v.username;
  return name ? String(name) : log.entity_id ? `#${log.entity_id}` : "";
}

export function ActivityFeed({
  items,
  showEntity = true,
  resolve,
}: {
  items: ActivityLog[];
  showEntity?: boolean;
  resolve?: ActivityResolver;
}) {
  return (
    <ol className="divide-y divide-line">
      {items.map((log) => (
        <li key={log.id} className="flex gap-3 px-4 py-3">
          <Avatar name={log.actor_name ?? "Hệ thống"} id={log.actor_id} size="sm" />
          <div className="min-w-0 flex-1 text-sm">
            <p>
              <span className="font-medium">{log.actor_name ?? "Hệ thống"}</span>{" "}
              <span className="text-ink-2">{labelOf(ACTION_LABEL, log.action).toLowerCase()}</span>{" "}
              {showEntity && (
                <span className="text-ink-2">
                  {labelOf(ENTITY_LABEL, log.entity_type).toLowerCase()}{" "}
                  <span className="font-medium text-ink">{subject(log, resolve)}</span>
                </span>
              )}
              {log.message && <span className="text-ink-3"> — {log.message}</span>}
            </p>
            <Changes log={log} resolve={resolve} />
          </div>
          <time
            dateTime={log.occurred_at}
            title={fmtDateTime(log.occurred_at)}
            className="shrink-0 text-xs whitespace-nowrap text-ink-3"
          >
            {fmtRelative(log.occurred_at)}
          </time>
        </li>
      ))}
    </ol>
  );
}
