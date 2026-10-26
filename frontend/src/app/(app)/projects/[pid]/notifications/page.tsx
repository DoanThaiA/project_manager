"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useEffect, useRef } from "react";

import { BotStatusBanner, TelegramChatCard, useTelegramLink } from "@/components/telegram-settings";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Empty, Spinner } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { useProjectId, useProjectPerms } from "@/lib/hooks";
import type { ProjectTelegram } from "@/lib/types";

export default function ProjectNotificationsPage() {
  const pid = useProjectId();
  const { can, loaded } = useProjectPerms(pid);
  const allowed = can("project.notification.manage");
  const base = `/projects/${pid}/telegram`;
  const link = useTelegramLink(`${base}/link`);
  const query = useQuery({
    queryKey: ["project", pid, "telegram"],
    queryFn: async () => (await api.get<ProjectTelegram>(base)).data,
    enabled: allowed,
    refetchInterval: link.waiting ? 3000 : false,
  });

  // Đang chờ thêm bot vào group: thấy thêm group mới thì thôi hỏi lại
  const count = query.data?.chats.length ?? 0;
  const before = useRef(count);
  const { waiting, stopWaiting } = link;
  useEffect(() => {
    if (!waiting) before.current = count;
    else if (count > before.current) stopWaiting();
  }, [count, waiting, stopWaiting]);

  if (!loaded) return <Spinner />;
  if (!allowed)
    return <Empty title="Không có quyền" description="Cần quyền cấu hình thông báo của dự án (project.notification.manage)." />;

  const addButton = (
    <Button variant="primary" size="sm" icon={<Plus className="size-4" />} loading={link.pending} onClick={link.open}>
      Thêm group Telegram
    </Button>
  );

  return (
    <Card className="max-w-3xl">
      <CardHeader title="Group Telegram nhận thông báo" action={query.data?.configured && addButton} />
      {query.isPending ? (
        <Spinner />
      ) : !query.data?.configured ? (
        <Empty
          title="Máy chủ chưa cấu hình bot Telegram"
          description="Quản trị viên cần đặt TELEGRAM_BOT_TOKEN (xem docs/DEPLOY.md mục 10)."
        />
      ) : (
        <>
          <BotStatusBanner bot={query.data.bot} />
          {link.waiting && (
            <p className="border-b border-line bg-brand-soft px-4 py-2.5 text-sm text-brand">
              Trong Telegram, chọn group để thêm bot — group sẽ tự hiện ở đây. Mỗi người trong dự án tự kết nối
              Telegram cá nhân ở mục <b>Thông báo Telegram</b> trên menu.
            </p>
          )}
          {query.data.chats.length === 0 ? (
            <Empty
              title="Chưa có group nào"
              description="Bấm “Thêm group Telegram”, chọn group của team — bot sẽ báo vào group mỗi khi công việc đổi trạng thái."
            />
          ) : (
            <div className="divide-y divide-line">
              {query.data.chats.map((chat) => (
                <TelegramChatCard
                  key={chat.id}
                  chat={chat}
                  basePath={`${base}/chats/${chat.id}`}
                  removeLabel="Gỡ group"
                  onChanged={() => query.refetch()}
                />
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  );
}
