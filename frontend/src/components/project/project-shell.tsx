"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { MetaBadge } from "@/components/ui/badge";
import { Empty, Spinner } from "@/components/ui/misc";
import { errorMessage } from "@/lib/api";
import { useProject, useProjectId, useProjectPerms } from "@/lib/hooks";
import { PROJECT_STATUS } from "@/lib/labels";
import { cn } from "@/lib/utils";

const TABS = [
  { slug: "", label: "Tổng quan" },
  { slug: "requirements", label: "Yêu cầu khách hàng", perm: "requirement.view" },
  { slug: "backlog", label: "Backlog", perm: "work_item.view" },
  { slug: "board", label: "Sprint board", perm: "work_item.view" },
  { slug: "work-logs", label: "Log công việc", perm: "work_log.view" },
  { slug: "members", label: "Thành viên" },
  { slug: "activity", label: "Nhật ký", perm: "activity_log.view" },
  { slug: "notifications", label: "Thông báo", perm: "project.notification.manage" },
];

/** Header + tab của trang dự án (client: đọc pid từ URL, quyền theo dự án). */
export function ProjectShell({ children }: { children: React.ReactNode }) {
  const pid = useProjectId();
  const pathname = usePathname();
  const project = useProject(pid);
  const { can, loaded } = useProjectPerms(pid);

  if (project.isPending) return <Spinner />;
  if (project.isError)
    return <Empty title="Không mở được dự án" description={errorMessage(project.error)} />;

  const base = `/projects/${pid}`;
  const p = project.data;

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-2 flex items-center gap-1 text-[13px] text-ink-3">
        <Link href="/projects" className="hover:text-ink">
          Dự án
        </Link>
        <ChevronRight className="size-3.5" />
        <span className="font-mono text-ink-2">{p.key}</span>
      </nav>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">{p.name}</h1>
        <MetaBadge meta={PROJECT_STATUS[p.status]} />
      </div>

      <div className="-mx-4 mb-6 overflow-x-auto border-b border-line px-4 sm:mx-0 sm:px-0">
        <nav className="flex min-w-max gap-1" aria-label="Mục dự án">
          {TABS.filter((t) => !t.perm || !loaded || can(t.perm)).map((t) => {
            const href = t.slug ? `${base}/${t.slug}` : base;
            const active = t.slug ? pathname.startsWith(href) : pathname === base;
            return (
              <Link
                key={t.slug}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "-mb-px border-b-2 px-3 py-2 text-[13px] font-medium whitespace-nowrap transition-colors",
                  active ? "border-brand text-brand" : "border-transparent text-ink-3 hover:text-ink",
                )}
              >
                {t.label}
              </Link>
            );
          })}
        </nav>
      </div>
      {children}
    </>
  );
}
