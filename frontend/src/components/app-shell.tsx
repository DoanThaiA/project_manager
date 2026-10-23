"use client";

import {
  Bell,
  Building2,
  ClipboardList,
  FolderKanban,
  History,
  KanbanSquare,
  LayoutDashboard,
  LogOut,
  Menu,
  ShieldCheck,
  Timer,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Avatar, Spinner } from "@/components/ui/misc";
import { useAuth } from "@/lib/auth";
import { useProjects } from "@/lib/hooks";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: typeof LayoutDashboard; perm?: string };

const MAIN_NAV: NavItem[] = [
  { href: "/", label: "Tổng quan", icon: LayoutDashboard },
  { href: "/projects", label: "Dự án", icon: FolderKanban },
  { href: "/timesheet", label: "Timesheet của tôi", icon: Timer },
  { href: "/settings/notifications", label: "Thông báo Telegram", icon: Bell },
  { href: "/customers", label: "Khách hàng", icon: Building2, perm: "customer.view" },
];

const ADMIN_NAV: NavItem[] = [
  { href: "/admin/users", label: "Người dùng", icon: Users, perm: "user.view" },
  { href: "/admin/roles", label: "Vai trò & quyền", icon: ShieldCheck, perm: "role.manage" },
  { href: "/admin/activity", label: "Nhật ký hệ thống", icon: History, perm: "activity_log.view" },
];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({ item, pathname, onClick }: { item: NavItem; pathname: string; onClick?: () => void }) {
  const active = isActive(pathname, item.href);
  return (
    <Link
      href={item.href}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition-colors",
        active ? "bg-brand-soft text-brand" : "text-ink-2 hover:bg-subtle hover:text-ink",
      )}
    >
      <item.icon className="size-4 shrink-0" />
      <span className="truncate">{item.label}</span>
    </Link>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { me, can, logout } = useAuth();
  const projects = useProjects({ status: "active" });
  const adminItems = ADMIN_NAV.filter((i) => !i.perm || can(i.perm));

  return (
    <div className="flex h-full flex-col">
      <Link href="/" className="flex items-center gap-2 px-4 py-4" onClick={onNavigate}>
        <span className="flex size-7 items-center justify-center rounded-md bg-brand text-white">
          <KanbanSquare className="size-4" />
        </span>
        <span className="font-semibold">Project Manager</span>
      </Link>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-4" aria-label="Điều hướng chính">
        <div className="space-y-0.5">
          {MAIN_NAV.filter((i) => !i.perm || can(i.perm)).map((item) => (
            <NavLink key={item.href} item={item} pathname={pathname} onClick={onNavigate} />
          ))}
        </div>

        {!!projects.data?.items.length && (
          <div>
            <p className="mb-1 px-2.5 text-[11px] font-semibold tracking-wide text-ink-3 uppercase">Dự án đang chạy</p>
            <div className="space-y-0.5">
              {projects.data.items.slice(0, 8).map((p) => (
                <NavLink
                  key={p.id}
                  pathname={pathname}
                  onClick={onNavigate}
                  item={{ href: `/projects/${p.id}`, label: `${p.key} · ${p.name}`, icon: ClipboardList }}
                />
              ))}
            </div>
          </div>
        )}

        {adminItems.length > 0 && (
          <div>
            <p className="mb-1 px-2.5 text-[11px] font-semibold tracking-wide text-ink-3 uppercase">Quản trị</p>
            <div className="space-y-0.5">
              {adminItems.map((item) => (
                <NavLink key={item.href} item={item} pathname={pathname} onClick={onNavigate} />
              ))}
            </div>
          </div>
        )}
      </nav>

      <div className="flex items-center gap-2.5 border-t border-line px-3 py-3">
        <Avatar name={me?.full_name} id={me?.id} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium">{me?.full_name}</p>
          <p className="truncate text-xs text-ink-3">{me?.job_title || me?.username}</p>
        </div>
        <button
          type="button"
          onClick={logout}
          aria-label="Đăng xuất"
          title="Đăng xuất"
          className="rounded-md p-1.5 text-ink-3 hover:bg-subtle hover:text-ink"
        >
          <LogOut className="size-4" />
        </button>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { ready, token, me, loadingMe } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    if (ready && !token) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [ready, token, pathname, router]);

  if (!ready || !token || loadingMe || !me) return <Spinner className="min-h-dvh" />;

  return (
    <div className="min-h-dvh lg:pl-60">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-line bg-surface lg:block">
        <Sidebar />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 bg-surface shadow-pop">
            <button
              type="button"
              aria-label="Đóng menu"
              onClick={() => setMobileOpen(false)}
              className="absolute top-4 right-3 rounded-md p-1 text-ink-3 hover:bg-subtle"
            >
              <X className="size-4" />
            </button>
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <header className="sticky top-0 z-20 flex h-12 items-center gap-2 border-b border-line bg-surface/90 px-4 backdrop-blur lg:hidden">
        <button
          type="button"
          aria-label="Mở menu"
          onClick={() => setMobileOpen(true)}
          className="rounded-md p-1.5 text-ink-2 hover:bg-subtle"
        >
          <Menu className="size-5" />
        </button>
        <span className="font-semibold">Project Manager</span>
      </header>

      <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8">{children}</main>
    </div>
  );
}
