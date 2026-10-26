"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { addDays, format, parseISO } from "date-fns";
import { useState } from "react";

import { ImageTextEditor } from "@/components/project/image-text-editor";
import { PASTE_HINT, useInlineImages } from "@/components/text-images";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useProject, useSprints } from "@/lib/hooks";
import type { Sprint } from "@/lib/types";
import { todayISO } from "@/lib/utils";

export function CreateSprintModal({ pid, onClose }: { pid: number; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: project } = useProject(pid);
  const { data: sprints = [] } = useSprints(pid);
  // Gợi ý ngày bắt đầu = ngày sau khi sprint gần nhất kết thúc
  const lastEnd = sprints.map((s) => s.end_date).sort().pop();
  const [startDate, setStartDate] = useState(lastEnd ? format(addDays(parseISO(lastEnd), 1), "yyyy-MM-dd") : todayISO());
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [capacity, setCapacity] = useState("");
  const duration = project?.sprint_duration_days ?? 14;
  const endDate = startDate ? format(addDays(parseISO(startDate), duration - 1), "yyyy-MM-dd") : "";

  const mutation = useMutation({
    mutationFn: async () =>
      (
        await api.post<Sprint>(`/projects/${pid}/sprints`, {
          name: name || null,
          goal: goal || null,
          start_date: startDate,
          capacity_hours: capacity ? Number(capacity) : null,
        })
      ).data,
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["project", pid, "sprints"] });
      toast.success(`Đã tạo ${s.name}`);
      onClose();
    },
    onError: toast.error,
  });

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title="Sprint mới"
      description={`Độ dài sprint của dự án: ${duration} ngày`}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button variant="primary" loading={mutation.isPending} disabled={!startDate} onClick={() => mutation.mutate()}>
            Tạo sprint
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Tên" hint="Bỏ trống: tự đặt Sprint N" className="sm:col-span-2">
          {(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="Ngày bắt đầu" required>
          {(id) => <Input id={id} type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />}
        </Field>
        <Field label="Ngày kết thúc">{(id) => <Input id={id} type="date" value={endDate} disabled />}</Field>
        <Field label="Sprint goal" className="sm:col-span-2">
          {(id) => <Textarea id={id} rows={2} value={goal} onChange={(e) => setGoal(e.target.value)} />}
        </Field>
        <Field label="Năng lực (giờ)" hint="Tổng giờ team có thể làm">
          {(id) => <Input id={id} type="number" min={0} value={capacity} onChange={(e) => setCapacity(e.target.value)} />}
        </Field>
      </div>
    </Modal>
  );
}

export function CompleteSprintModal({
  pid,
  sprint,
  unfinished,
  onClose,
}: {
  pid: number;
  sprint: Sprint;
  unfinished: number;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: sprints = [] } = useSprints(pid);
  const planned = sprints.filter((s) => s.status === "planned");
  const [target, setTarget] = useState<string>("backlog");
  const [review, setReview] = useState(sprint.review_note ?? "");
  const [retro, setRetro] = useState(sprint.retrospective_note ?? "");
  const images = useInlineImages(pid, [review, retro], "sprints");

  const mutation = useMutation({
    mutationFn: () =>
      api.post(`/projects/${pid}/sprints/${sprint.id}/complete`, {
        move_unfinished_to: target === "backlog" ? "backlog" : "next_sprint",
        next_sprint_id: target === "backlog" ? null : Number(target),
        review_note: review || null,
        retrospective_note: retro || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", pid] });
      toast.success(`Đã kết thúc ${sprint.name}`);
      onClose();
    },
    onError: toast.error,
  });

  return (
    <Modal
      open
      onClose={onClose}
      title={`Kết thúc ${sprint.name}`}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button
            variant="primary"
            loading={mutation.isPending}
            disabled={images.uploading > 0}
            onClick={() => mutation.mutate()}
          >
            Kết thúc sprint
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {unfinished > 0 ? (
          <Field label={`${unfinished} công việc chưa xong sẽ chuyển tới`}>
            {(id) => (
              <Select id={id} value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="backlog">Product Backlog</option>
                {planned.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        ) : (
          <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            Tất cả công việc trong sprint đã hoàn thành.
          </p>
        )}
        <Field label="Sprint Review" hint={`Kết quả demo, phản hồi của khách hàng. ${PASTE_HINT}`}>
          {(id) => <ImageTextEditor id={id} rows={3} value={review} onChange={setReview} source={images.source} />}
        </Field>
        <Field label="Sprint Retrospective" hint={`Điều làm tốt, cần cải thiện, hành động. ${PASTE_HINT}`}>
          {(id) => <ImageTextEditor id={id} rows={3} value={retro} onChange={setRetro} source={images.source} />}
        </Field>
      </div>
    </Modal>
  );
}
