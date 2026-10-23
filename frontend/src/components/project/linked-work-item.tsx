"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { WorkItemModal } from "@/components/project/work-item-modal";
import { api } from "@/lib/api";
import type { WorkItem } from "@/lib/types";

/** Mở công việc theo `?item=<id>` trên URL (link trong tin nhắn Telegram). */
export function LinkedWorkItem({ pid }: { pid: number }) {
  // useSearchParams cần Suspense để Next.js vẫn prerender được phần còn lại của trang
  return (
    <Suspense fallback={null}>
      <LinkedWorkItemInner pid={pid} />
    </Suspense>
  );
}

function LinkedWorkItemInner({ pid }: { pid: number }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const id = Number(params.get("item")) || null;
  const item = useQuery({
    queryKey: ["project", pid, "work-items", id],
    queryFn: async () => (await api.get<WorkItem>(`/projects/${pid}/work-items/${id}`)).data,
    enabled: !!id,
  });
  if (!id || !item.data) return null;
  return (
    <WorkItemModal
      key={id}
      pid={pid}
      item={item.data}
      onClose={() => router.replace(pathname, { scroll: false })}
    />
  );
}
