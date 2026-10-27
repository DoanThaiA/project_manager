"use client";

import { useMutation } from "@tanstack/react-query";
import { Send, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox, Select } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import {
  BOARD_COLUMNS,
  REQUIREMENT_STATUS,
  SPRINT_STATUS,
  WORK_ITEM_STATUS,
} from "@/lib/labels";
import type {
  MyTelegram,
  NotificationEvent,
  NotificationSubscription,
  TelegramChat,
  TelegramLink,
} from "@/lib/types";
import { cn, fmtDateTime } from "@/lib/utils";

type Options = Record<string, { label: string }>;

/** Các loại thông báo — khớp NotificationEvent / events.SPECS ở backend. */
const EVENT_GROUPS: {
  title: string;
  events: {
    event: NotificationEvent;
    label: string;
    personalLabel?: string;
    /** Nhãn phạm vi "của tôi" (chat cá nhân); không có = sự kiện không phân biệt phạm vi */
    mine?: string;
    /** Lọc theo trạng thái mới */
    statuses?: { options: Options; values: string[] };
  }[];
}[] = [
  {
    title: "Công việc",
    events: [
      {
        event: "work_item.status_changed",
        label: "Công việc đổi trạng thái (Sprint board, backlog)",
        mine: "Giao cho tôi hoặc do tôi tạo",
        statuses: {
          options: WORK_ITEM_STATUS,
          values: ["backlog", ...BOARD_COLUMNS, "cancelled"],
        },
      },
      { event: "work_item.created", label: "Công việc mới được tạo" },
      {
        event: "work_item.assigned",
        label: "Giao việc (thêm người phụ trách)",
        personalLabel: "Tôi được giao việc",
      },
    ],
  },
  {
    title: "Log công việc",
    events: [
      {
        event: "work_log.created",
        label: "Có log công việc mới",
        mine: "Log trên công việc / yêu cầu của tôi",
      },
    ],
  },
  {
    title: "Yêu cầu khách hàng",
    events: [
      {
        event: "requirement.created",
        label: "Yêu cầu mới",
        mine: "Yêu cầu tôi phụ trách",
      },
      {
        event: "requirement.status_changed",
        label: "Yêu cầu đổi trạng thái",
        mine: "Yêu cầu tôi phụ trách hoặc do tôi tạo",
        statuses: {
          options: REQUIREMENT_STATUS,
          values: Object.keys(REQUIREMENT_STATUS),
        },
      },
      {
        event: "requirement.commented",
        label: "Bình luận mới trên yêu cầu",
        mine: "Yêu cầu tôi phụ trách, tạo hoặc đã bình luận",
      },
    ],
  },
  {
    title: "Sprint",
    events: [
      {
        event: "sprint.status_changed",
        label: "Sprint bắt đầu / kết thúc / huỷ",
        statuses: {
          options: SPRINT_STATUS,
          values: ["active", "completed", "cancelled"],
        },
      },
    ],
  },
];

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
    const timer = setTimeout(
      () => setWaitingUntil(null),
      Math.max(0, waitingUntil - Date.now()),
    );
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

/** Một chat đã liên kết: trạng thái, các loại thông báo nhận, gửi thử, gỡ. */
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

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 font-medium">
            <span className="truncate">
              {chat.title || (personal ? "Chat riêng" : "Group")}
            </span>
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
          <Button
            size="sm"
            icon={<Send className="size-4" />}
            loading={test.isPending}
            onClick={() => test.mutate()}
          >
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

      <div className="divide-y divide-line rounded-lg bg-subtle">
        {EVENT_GROUPS.map((group) => (
          <section key={group.title} className="space-y-3 px-4 py-3">
            <h4 className="text-xs font-semibold tracking-wide text-ink-3 uppercase">
              {group.title}
            </h4>
            {group.events.map((cfg) => (
              <EventSetting
                key={cfg.event}
                cfg={cfg}
                sub={chat.subscriptions.find((s) => s.event === cfg.event)}
                personal={personal}
                basePath={basePath}
                onChanged={onChanged}
              />
            ))}
          </section>
        ))}
        <p className="px-4 py-3 text-xs text-ink-3">
          {personal
            ? "Không báo các thay đổi do chính bạn thực hiện; chỉ báo những gì bạn còn quyền xem trong dự án."
            : "Nhiều thay đổi cùng loại trong một lần thao tác (vd: kết thúc sprint) được gộp thành một tin."}
        </p>
      </div>
    </div>
  );
}

/** Bật / tắt một loại thông báo, kèm phạm vi (chat cá nhân) và lọc trạng thái. */
function EventSetting({
  cfg,
  sub,
  personal,
  basePath,
  onChanged,
}: {
  cfg: (typeof EVENT_GROUPS)[number]["events"][number];
  sub?: NotificationSubscription;
  personal?: boolean;
  basePath: string;
  onChanged: () => void;
}) {
  const toast = useToast();
  const save = useMutation({
    mutationFn: (
      body: Pick<NotificationSubscription, "enabled" | "scope" | "statuses">,
    ) => api.put(`${basePath}/subscriptions/${cfg.event}`, body),
    onSuccess: onChanged,
    onError: toast.error,
  });

  // Chưa có dòng đăng ký = chưa nhận
  const current = {
    enabled: sub?.enabled ?? false,
    scope: sub?.scope ?? (personal && cfg.mine ? "mine" : "all"),
    statuses: sub?.statuses ?? [],
  };
  const update = (patch: Partial<typeof current>) =>
    save.mutate({ ...current, ...patch });
  const toggleStatus = (s: string) =>
    update({
      statuses: current.statuses.includes(s)
        ? current.statuses.filter((x) => x !== s)
        : [...current.statuses, s],
    });

  return (
    <div className="space-y-2">
      <Checkbox
        label={
          <span className="font-medium text-ink">
            {(personal && cfg.personalLabel) || cfg.label}
          </span>
        }
        checked={current.enabled}
        disabled={save.isPending}
        onChange={(e) => update({ enabled: e.target.checked })}
      />
      {current.enabled && ((personal && cfg.mine) || cfg.statuses) && (
        <div className="ml-6 space-y-2">
          {personal && cfg.mine && (
            <Select
              aria-label="Phạm vi"
              className="h-8 w-auto text-[13px]"
              value={current.scope}
              disabled={save.isPending}
              onChange={(e) =>
                update({ scope: e.target.value as typeof current.scope })
              }
            >
              <option value="mine">{cfg.mine}</option>
              <option value="all">Mọi thứ trong các dự án tôi tham gia</option>
            </Select>
          )}
          {cfg.statuses && (
            <div>
              <p className="mb-1.5 text-xs text-ink-3">
                Khi chuyển sang trạng thái (
                {current.statuses.length
                  ? "chỉ các trạng thái đã chọn"
                  : "không chọn = mọi trạng thái"}
                )
              </p>
              <div className="flex flex-wrap gap-1.5">
                {cfg.statuses.values.map((s) => {
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
                      {cfg.statuses!.options[s]?.label ?? s}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Cảnh báo khi bot không nhận được lệnh (chưa chạy, lỗi kết nối, token bị nơi khác dùng). */
export function BotStatusBanner({ bot }: { bot: MyTelegram["bot"] }) {
  // Bot hỏi Telegram ~30 giây / lần; quá 2 phút không hỏi được là có vấn đề
  const [now] = useState(() => Date.now());
  const stale =
    !bot.last_poll_at ||
    now - new Date(bot.last_poll_at).getTime() > 2 * 60 * 1000;
  if (bot.running && !bot.error && !stale) return null;
  return (
    <p className="border-b border-line bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
      ⚠️ Bot chưa nhận được lệnh từ Telegram nên chưa liên kết được chat mới.{" "}
      {bot.error ??
        (bot.running
          ? "Đang kết nối tới Telegram…"
          : "Tác vụ nhận lệnh của bot không chạy.")}{" "}
      Xem log: <code>docker compose logs api | grep -i telegram</code>
    </p>
  );
}
