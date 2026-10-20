"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { EnumSelect } from "@/components/project/selects";
import { Button } from "@/components/ui/button";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useProjects } from "@/lib/hooks";
import { ACTIVITY_TYPE } from "@/lib/labels";
import type { ActivityType, WorkItem, WorkLog } from "@/lib/types";
import { num, todayISO } from "@/lib/utils";

/** Modal ghi log công việc. Không truyền pid -> cho chọn dự án. */
export function WorkLogModal({
  open,
  onClose,
  pid,
  workItem,
  requirementId,
  log,
}: {
  open: boolean;
  onClose: () => void;
  pid?: number;
  workItem?: WorkItem;
  requirementId?: number;
  log?: WorkLog; // sửa log có sẵn
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const projects = useProjects({});
  const [projectId, setProjectId] = useState<number | null>(pid ?? log?.project_id ?? null);
  const [logDate, setLogDate] = useState(log?.log_date ?? todayISO());
  const [hours, setHours] = useState(log ? String(num(log.hours)) : "");
  const [activity, setActivity] = useState<ActivityType>(
    log?.activity_type ?? (workItem?.type === "bug" ? "testing" : "development"),
  );
  const [description, setDescription] = useState(log?.description ?? "");
  const [billable, setBillable] = useState(log?.is_billable ?? true);
  const [remaining, setRemaining] = useState("");

  const mutation = useMutation({
    mutationFn: async () => {
      if (log) {
        return api.patch(`/projects/${log.project_id}/work-logs/${log.id}`, {
          log_date: logDate,
          hours: Number(hours),
          activity_type: activity,
          description,
          is_billable: billable,
        });
      }
      return api.post(`/projects/${projectId}/work-logs`, {
        work_item_id: workItem?.id ?? null,
        requirement_id: requirementId ?? null,
        log_date: logDate,
        hours: Number(hours),
        activity_type: activity,
        description,
        is_billable: billable,
        remaining_hours: remaining ? Number(remaining) : null,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["me", "work-logs"] });
      toast.success(log ? "Đã cập nhật log" : `Đã ghi ${hours}h`);
      onClose();
    },
    onError: toast.error,
  });

  const valid = !!projectId && Number(hours) > 0 && Number(hours) <= 24 && description.trim() && logDate;

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="md"
      title={log ? "Sửa log công việc" : "Ghi log công việc"}
      description={workItem ? `${workItem.code} · ${workItem.title}` : undefined}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button variant="primary" loading={mutation.isPending} disabled={!valid} onClick={() => mutation.mutate()}>
            Lưu log
          </Button>
        </>
      }
    >
      <form
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) mutation.mutate();
        }}
      >
        {!pid && !log && (
          <Field label="Dự án" required className="sm:col-span-2">
            {(id) => (
              <Select
                id={id}
                value={projectId ?? ""}
                onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">— Chọn dự án —</option>
                {projects.data?.items.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.key} · {p.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
        <Field label="Ngày" required>
          {(id) => <Input id={id} type="date" max={todayISO()} value={logDate} onChange={(e) => setLogDate(e.target.value)} />}
        </Field>
        <Field label="Số giờ" required>
          {(id) => (
            <Input
              id={id}
              type="number"
              min={0.25}
              max={24}
              step={0.25}
              autoFocus
              value={hours}
              onChange={(e) => setHours(e.target.value)}
            />
          )}
        </Field>
        <Field label="Loại công việc">
          {(id) => <EnumSelect id={id} options={ACTIVITY_TYPE} value={activity} onChange={(v) => v && setActivity(v)} />}
        </Field>
        {workItem && !log && (
          <Field
            label="Giờ còn lại"
            hint={`Bỏ trống: tự trừ (hiện còn ${num(workItem.remaining_hours)}h)`}
          >
            {(id) => (
              <Input id={id} type="number" min={0} step={0.5} value={remaining} onChange={(e) => setRemaining(e.target.value)} />
            )}
          </Field>
        )}
        <Field label="Nội dung đã làm" required className="sm:col-span-2">
          {(id) => <Textarea id={id} rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />}
        </Field>
        <Checkbox
          className="sm:col-span-2"
          label="Tính phí cho khách hàng"
          checked={billable}
          onChange={(e) => setBillable(e.target.checked)}
        />
        <button type="submit" hidden />
      </form>
    </Modal>
  );
}
