"use client";

import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";

import { ProjectFormModal } from "@/components/project/project-form";
import { EnumSelect } from "@/components/project/selects";
import { MetaBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { Card, Empty, PageHeader, Spinner, Table } from "@/components/ui/misc";
import { clean } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useProjects } from "@/lib/hooks";
import { PROJECT_STATUS } from "@/lib/labels";
import type { ProjectStatus } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

export default function ProjectsPage() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<ProjectStatus | "">("");
  const [creating, setCreating] = useState(false);
  const query = useProjects(clean({ q: useDeferredValue(q), status }));

  return (
    <>
      <PageHeader
        title="Dự án"
        description="Các dự án bạn có quyền xem"
        actions={
          can("project.create") && (
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
              Dự án mới
            </Button>
          )
        }
      />

      <Card>
        <div className="flex flex-wrap gap-2 border-b border-line p-3">
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-3" />
            <Input
              aria-label="Tìm dự án"
              placeholder="Tìm theo mã, tên…"
              className="pl-8"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <EnumSelect
            aria-label="Lọc trạng thái"
            className="w-44"
            options={PROJECT_STATUS}
            value={status}
            onChange={setStatus}
            emptyLabel="Mọi trạng thái"
          />
        </div>

        {query.isPending ? (
          <Spinner />
        ) : !query.data?.items.length ? (
          <Empty title="Không có dự án nào" />
        ) : (
          <Table>
            <thead>
              <tr>
                <th className="w-24">Mã</th>
                <th>Tên dự án</th>
                <th>Trạng thái</th>
                <th>Bắt đầu</th>
                <th>Kết thúc</th>
                <th className="text-right">Sprint</th>
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((p) => (
                <tr key={p.id}>
                  <td className="font-mono text-xs font-semibold text-ink-2">{p.key}</td>
                  <td>
                    <Link href={`/projects/${p.id}`} className="font-medium hover:text-brand hover:underline">
                      {p.name}
                    </Link>
                    {p.description && <p className="max-w-lg truncate text-xs text-ink-3">{p.description}</p>}
                  </td>
                  <td>
                    <MetaBadge meta={PROJECT_STATUS[p.status]} />
                  </td>
                  <td className="tabular-nums">{fmtDate(p.start_date)}</td>
                  <td className="tabular-nums">{fmtDate(p.end_date)}</td>
                  <td className="text-right tabular-nums">{p.sprint_duration_days} ngày</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {creating && <ProjectFormModal onClose={() => setCreating(false)} />}
    </>
  );
}
