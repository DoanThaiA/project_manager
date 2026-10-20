"use client";

import { ActivityPage } from "@/components/activity-page";
import { PageHeader } from "@/components/ui/misc";

export default function SystemActivityPage() {
  return (
    <>
      <PageHeader title="Nhật ký hệ thống" description="Mọi thay đổi dữ liệu, đăng nhập và đăng nhập thất bại" />
      <ActivityPage endpoint="/activity-logs" queryKey={["activity", "system"]} />
    </>
  );
}
