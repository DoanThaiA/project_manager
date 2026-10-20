"use client";

import { ActivityPage } from "@/components/activity-page";
import { useProjectActivityResolver } from "@/lib/activity-resolver";
import { useProjectId } from "@/lib/hooks";

export default function ProjectActivityPage() {
  const pid = useProjectId();
  const resolve = useProjectActivityResolver(pid);
  return (
    <ActivityPage endpoint={`/projects/${pid}/activity-logs`} queryKey={["project", pid, "activity"]} resolve={resolve} />
  );
}
