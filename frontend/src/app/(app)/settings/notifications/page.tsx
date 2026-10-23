"use client";

import { useQuery } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useEffect, useRef } from "react";

import { TelegramChatCard, useTelegramLink } from "@/components/telegram-settings";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Empty, PageHeader, Spinner } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { MyTelegram } from "@/lib/types";

export default function MyNotificationsPage() {
  const link = useTelegramLink("/me/telegram/link");
  const query = useQuery({
    queryKey: ["me", "telegram"],
    queryFn: async () => (await api.get<MyTelegram>("/me/telegram")).data,
    // Đang chờ người dùng bấm Start trong Telegram: hỏi lại mỗi 3 giây
    refetchInterval: link.waiting ? 3000 : false,
  });
  const chat = query.data?.chat;

  // Đang chờ: thấy liên kết mới (lần đầu, hoặc đổi sang tài khoản Telegram khác) thì thôi hỏi lại
  const linkedAt = chat?.linked_at ?? null;
  const before = useRef(linkedAt);
  const { waiting, stopWaiting } = link;
  useEffect(() => {
    if (!waiting) before.current = linkedAt;
    else if (linkedAt !== before.current) stopWaiting();
  }, [linkedAt, waiting, stopWaiting]);

  return (
    <>
      <PageHeader
        title="Thông báo Telegram"
        description="Nhận tin trên Telegram khi công việc liên quan tới bạn được đổi trạng thái."
      />
      <Card className="max-w-3xl">
        <CardHeader
          title="Telegram cá nhân"
          action={
            query.data?.configured &&
            chat && (
              <Button size="sm" loading={link.pending} onClick={link.open}>
                Kết nối tài khoản khác
              </Button>
            )
          }
        />
        {query.isPending ? (
          <Spinner />
        ) : !query.data?.configured ? (
          <Empty
            title="Máy chủ chưa cấu hình bot Telegram"
            description="Quản trị viên cần đặt TELEGRAM_BOT_TOKEN (xem docs/DEPLOY.md mục 10)."
          />
        ) : chat ? (
          <TelegramChatCard
            chat={chat}
            personal
            basePath="/me/telegram"
            removeLabel="Ngắt kết nối"
            onChanged={() => query.refetch()}
          />
        ) : (
          <Empty
            title={link.waiting ? "Đang chờ bạn bấm Start trong Telegram…" : "Chưa kết nối Telegram"}
            description={
              link.waiting
                ? "Trong Telegram, bấm nút Start ở chat với bot. Trang sẽ tự cập nhật."
                : "Bấm nút bên dưới, Telegram mở chat với bot — bấm Start là xong."
            }
            action={
              <Button variant="primary" icon={<Send className="size-4" />} loading={link.pending} onClick={link.open}>
                {link.waiting ? "Mở lại Telegram" : "Kết nối Telegram"}
              </Button>
            }
          />
        )}
      </Card>
    </>
  );
}
