"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useCallback, useMemo } from "react";

import { api } from "./api";
import { useAuth } from "./auth";
import type { Member, Page, Project, Role, Sprint } from "./types";

/** project_id từ URL /projects/[pid]/... */
export function useProjectId(): number {
  const params = useParams<{ pid: string }>();
  return Number(params.pid);
}

export function useProject(pid: number) {
  return useQuery({
    queryKey: ["project", pid],
    queryFn: async () => (await api.get<Project>(`/projects/${pid}`)).data,
    enabled: pid > 0,
  });
}

export function useProjects(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: ["projects", params],
    queryFn: async () => (await api.get<Page<Project>>("/projects", { params: { size: 100, ...params } })).data,
  });
}

/** Quyền của người dùng hiện tại trong dự án. */
export function useProjectPerms(pid: number) {
  const { me } = useAuth();
  const query = useQuery({
    queryKey: ["project", pid, "perms"],
    queryFn: async () => (await api.get<string[]>(`/projects/${pid}/my-permissions`)).data,
    enabled: pid > 0,
    staleTime: 60_000,
  });
  const set = useMemo(() => new Set(query.data ?? []), [query.data]);
  const can = useCallback((code: string) => !!me?.is_system_admin || set.has(code), [me, set]);
  return { can, loaded: query.isSuccess };
}

export function useMembers(pid: number) {
  const query = useQuery({
    queryKey: ["project", pid, "members"],
    queryFn: async () => (await api.get<Member[]>(`/projects/${pid}/members`)).data,
    enabled: pid > 0,
  });
  const byId = useMemo(() => new Map((query.data ?? []).map((m) => [m.user.id, m.user])), [query.data]);
  return { ...query, members: query.data ?? [], byId };
}

export function useSprints(pid: number, enabled = true) {
  return useQuery({
    queryKey: ["project", pid, "sprints"],
    queryFn: async () => (await api.get<Sprint[]>(`/projects/${pid}/sprints`)).data,
    enabled: pid > 0 && enabled,
  });
}

export function useRoles() {
  return useQuery({
    queryKey: ["roles"],
    queryFn: async () => (await api.get<Role[]>("/roles")).data,
    staleTime: 5 * 60_000,
  });
}
