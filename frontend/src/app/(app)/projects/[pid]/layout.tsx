import { Suspense } from "react";

import { ProjectShell } from "@/components/project/project-shell";
import { Spinner } from "@/components/ui/misc";

// Layout server: Suspense cho phần client đọc params, để Next render được khung trang ngay khi điều hướng
export default function ProjectLayout({ children }: LayoutProps<"/projects/[pid]">) {
  return (
    <Suspense fallback={<Spinner />}>
      <ProjectShell>{children}</ProjectShell>
    </Suspense>
  );
}
