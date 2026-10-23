"use client";

import { useMutation } from "@tanstack/react-query";
import { Send, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox, Select } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { BOARD_COLUMNS, WORK_ITEM_STATUS } from "@/lib/labels";
import type { NotificationSubscription, TelegramChat, TelegramLink, WorkItemStatus } from "@/lib/types";
import { cn, fmtDateTime } from "@/lib/utils";

export const STATUS_EVENT = "work_item.status_changed";
const FILTER_STATUSES: WorkItemStatus[] = ["backlog", ...BOARD_COLUMNS, "cancelled"];

/**
 * Mở link t.me do máy chủ tạo. Mở tab trống ngay trong lúc bấm (tránh trình chặn popup) rồi mới gán địa chỉ.
 * Sau đó trang hỏi lại máy chủ định kỳ (`waiting`) để thấy chat vừa liên kết.
 */
export function useTelegramLink(path: string) {
  const toast = useToast();
  // Hạn của mã liên kết đang chờ người dùng bấm Start (null: không chờ)
  const [waitingUntil, setWaitingUntil] = useState<number | null>(null);
  useEffect(() => {
    if (waitingUntil === null) return;
    const timer = setTimeout(() => setWaitingUntil(null), Math.max(0, waitingUntil - Date.now()));
    return () => clearTimeout(timer);
  }, [waitingUntil]);
  const stopWaiting = useCallback(() => setWaitingUntil(null), []);
  const mutation = useMutation({
    mutationFn: async (tab: Window | null) => {
      const link = (await api.post<TelegramLink>(path)).data;
      if (tab) tab.location.href = link.url;
      else window.location.href = link.url;
      return link;
    },
    onSuccess: (link) => setWaitingUntil(new Date(link.expires_at).getTime()),
    onError: (err, tab) => {
      tab?.close();
      toast.error(err);
    },
  });
  return {
    open: () => mutation.mutate(window.open("", "_blank")),
    pending: mutation.isPending,
    waiting: waitingUntil !== null,
    stopWaiting,
  };
}

/** Một chat đã liên kết: trạng thái, bộ lọc trạng thái công việc, gửi thử, gỡ. */
export function TelegramChatCard({
  chat,
  personal,
  basePath,
  onChanged,
  removeLabel,
}: {
  chat: TelegramChat;
  personal?: boolean;
  /** /me/telegram hoặc /projects/{pid}/telegram/chats/{id} */
  basePath: string;
  onChanged: () => void;
  removeLabel: string;
}) {
  const toast = useToast();
  const sub = chat.subscriptions.find((s) => s.event === STATUS_EVENT);
  const save = useMutation({
    mutationFn: (body: Pick<NotificationSubscription, "enabled" | "scope" | "statuses">) =>
      api.put(`${basePath}/subscriptions/${STATUS_EVENT}`, body),
    onSuccess: onChanged,
    onError: toast.error,
  });
  const test = useMutation({
    mutationFn: () => api.post(`${basePath}/test`),
    onSuccess: () => {
      toast.success("Đã gửi tin thử — kiểm tra Telegram");
      onChanged();
    },
    onError: (err) => {
      toast.error(err);
      onChanged();
    },
  });
  const remove = useMutation({
    mutationFn: () => api.delete(basePath),
    onSuccess: onChanged,
    onError: toast.error,
  });

  const current = {
    enabled: sub?.enabled ?? true,
    scope: sub?.scope ?? (personal ? "mine" : "all"),
    statuses: sub?.statuses ?? [],
  };
  const update = (patch: Partial<typeof current>) => save.mutate({ ...current, ...patch });
  const toggleStatus = (s: WorkItemStatus) =>
    update({
      statuses: current.statuses.includes(s) ? current.statuses.filter((x) => x !== s) : [...current.statuses, s],
    });

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 font-medium">
            <span className="truncate">{chat.title || (personal ? "Chat riêng" : "Group")}</span>
            {chat.is_active ? (
              <Badge tone="green">Đang nhận</Badge>
            ) : (
              <Badge tone="red">Không gửi được</Badge>
            )}
          </p>
          <p className="text-xs text-ink-3">
            {chat.is_active
              ? `Liên kết lúc ${fmtDateTime(chat.linked_at)}`
              : personal
                ? "Bạn đã chặn bot? Bỏ chặn rồi bấm Gửi thử, hoặc kết nối lại."
                : "Bot đã bị xoá khỏi group? Thêm lại bot rồi bấm Gửi thử, hoặc liên kết lại."}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" icon={<Send className="size-4" />} loading={test.isPending} onClick={() => test.mutate()}>
            Gửi thử
          </Button>
          <Button
            size="sm"
            variant="ghost"
            icon={<Trash2 className="size-4" />}
            loading={remove.isPending}
            onClick={() => confirm(`${removeLabel}?`) && remove.mutate()}
          >
            {removeLabel}
          </Button>
        </div>
      </div>

      <div className="space-y-3 rounded-lg bg-subtle px-4 py-3">
        <Checkbox
          label={<span className="font-medium text-ink">Báo khi công việc đổi trạng thái (Sprint board, backlog)</span>}
          checked={current.enabled}
          disabled={save.isPending}
          onChange={(e) => update({ enabled: e.target.checked })}
        />
        {current.enabled && (
          <>
            {personal && (
              <label className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
                Công việc:
                <Select
                  className="w-auto"
                  value={current.scope}
                  disabled={save.isPending}
                  onChange={(e) => update({ scope: e.target.value as typeof current.scope })}
                >
                  <option value="mine">Giao cho tôi hoặc do tôi tạo</option>
                  <option value="all">Mọi công việc trong các dự án tôi tham gia</option>
                </Select>
              </label>
            )}
            <div>
              <p className="mb-1.5 text-sm text-ink-2">
                Khi chuyển sang trạng thái{" "}
                <span className="text-ink-3">
                  ({current.statuses.length ? "chỉ các trạng thái đã chọn" : "không chọn = mọi trạng thái"})
                </span>
              </p>
              <div className="flex flex-wrap gap-1.5">
                {FILTER_STATUSES.map((s) => {
                  const on = current.statuses.includes(s);
                  return (
                    <button
                      key={s}
                      type="button"
                      aria-pressed={on}
                      disabled={save.isPending}
                      onClick={() => toggleStatus(s)}
                      className={cn(
                        "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                        on
                          ? "border-brand bg-brand-soft text-brand"
                          : "border-line-strong text-ink-2 hover:border-brand hover:text-brand",
                      )}
                    >
                      {WORK_ITEM_STATUS[s].label}
                    </button>
                  );
                })}
              </div>
            </div>
            <p className="text-xs text-ink-3">
              {personal
                ? "Không báo các thay đổi do chính bạn thực hiện."
                : "Nhiều công việc đổi trạng thái cùng lúc (vd: kết thúc sprint) được gộp thành một tin."}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
