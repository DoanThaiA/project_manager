"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ActivityFeed, type ActivityResolver } from "@/components/activity-feed";
import { Input, Select } from "@/components/ui/form";
import { Card, Empty, Pagination, Spinner } from "@/components/ui/misc";
import { api, clean } from "@/lib/api";
import { ACTION_LABEL, ENTITY_LABEL } from "@/lib/labels";
import type { ActivityLog, Page } from "@/lib/types";

/** Danh sách nhật ký hoạt động có lọc; dùng cho dự án và toàn hệ thống. */
export function ActivityPage({
  endpoint,
  queryKey,
  resolve,
}: {
  endpoint: string;
  queryKey: unknown[];
  resolve?: ActivityResolver;
}) {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ entity_type: "", action: "", date_from: "", date_to: "" });
  const setFilter = (k: keyof typeof filters, v: string) => {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(1);
  };
  const params = clean({ ...filters, page, size: 50 });
  const logs = useQuery({
    queryKey: [...queryKey, params],
    queryFn: async () => (await api.get<Page<ActivityLog>>(endpoint, { params })).data,
    placeholderData: keepPreviousData,
  });

  return (
    <Card>
      <div className="flex flex-wrap gap-2 border-b border-line p-3">
        <Select
          aria-label="Đối tượng"
          className="w-40"
          value={filters.entity_type}
          onChange={(e) => setFilter("entity_type", e.target.value)}
        >
          <option value="">Mọi đối tượng</option>
          {Object.entries(ENTITY_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </Select>
        <Select aria-label="Hành động" className="w-44" value={filters.action} onChange={(e) => setFilter("action", e.target.value)}>
          <option value="">Mọi hành động</option>
          {Object.entries(ACTION_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </Select>
        <Input
          aria-label="Từ ngày"
          type="date"
          className="w-38"
          value={filters.date_from}
          onChange={(e) => setFilter("date_from", e.target.value)}
        />
        <Input
          aria-label="Đến ngày"
          type="date"
          className="w-38"
          value={filters.date_to}
          onChange={(e) => setFilter("date_to", e.target.value)}
        />
      </div>
      {logs.isPending ? (
        <Spinner />
      ) : !logs.data?.items.length ? (
        <Empty title="Không có hoạt động nào" />
      ) : (
        <ActivityFeed items={logs.data.items} resolve={resolve} />
      )}
      {logs.data && <Pagination page={page} size={logs.data.size} total={logs.data.total} onChange={setPage} />}
    </Card>
  );
}
