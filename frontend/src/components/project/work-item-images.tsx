"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Loader2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { Attachment, AttachmentCategory } from "@/lib/types";
import { cn } from "@/lib/utils";

export const CATEGORIES: { key: AttachmentCategory; label: string; hint: string }[] = [
  { key: "bug", label: "Ảnh lỗi", hint: "Chụp màn hình phần đang lỗi" },
  { key: "result", label: "Ảnh sau khi sửa", hint: "Kết quả sau khi sửa xong" },
];
export const CATEGORY_LABEL: Record<AttachmentCategory, string> = { bug: "Ảnh lỗi", result: "Ảnh sau khi sửa" };
const ACCEPT = "image/png,image/jpeg,image/gif,image/webp";
const MAX_MB = 10;

/** Ảnh chọn khi đang tạo công việc mới — tải lên Cloudflare sau khi công việc được tạo. */
type PendingImage = { id: string; file: File; category: AttachmentCategory; preview: string };

async function uploadImage(pid: number, itemId: number, file: File, category: AttachmentCategory) {
  const body = new FormData();
  body.append("file", file);
  body.append("category", category);
  return (await api.post<Attachment>(`/projects/${pid}/work-items/${itemId}/attachments`, body)).data;
}

/** Lọc file ảnh hợp lệ; ảnh dán từ clipboard thường tên "image.png" nên đặt lại tên theo thời gian. */
function pickImages(files: Iterable<File>, onReject: (msg: string) => void): File[] {
  const ok: File[] = [];
  const stamp = Date.now();
  for (const f of files) {
    if (!ACCEPT.split(",").includes(f.type)) onReject(`${f.name}: chỉ nhận ảnh PNG, JPEG, GIF, WebP`);
    else if (f.size > MAX_MB * 1024 * 1024) onReject(`${f.name}: vượt quá ${MAX_MB} MB`);
    else if (f.name === "image.png") ok.push(new File([f], `screenshot-${stamp + ok.length}.png`, { type: f.type }));
    else ok.push(f);
  }
  return ok;
}

type Thumb = { key: string | number; src: string; name: string; uploading?: boolean; onRemove?: () => void };

export type WorkItemImagesState = ReturnType<typeof useWorkItemImages>;

/**
 * Trạng thái ảnh lỗi / ảnh sau khi sửa của công việc, dùng chung cho khu "Hình ảnh" và ô dán ảnh
 * trong Mô tả / Tiêu chí hoàn thành. Có `itemId`: tải thẳng lên ngay; không có (form tạo mới):
 * giữ trong `pending`, gọi uploadPending sau khi tạo công việc.
 */
export function useWorkItemImages({
  pid,
  itemId,
  canEdit,
  onRemoved,
}: {
  pid: number;
  itemId?: number;
  canEdit: boolean;
  /** Ảnh vừa bị xoá — để form bỏ dấu [Ảnh ...] tương ứng trong văn bản. */
  onRemoved?: (name: string, category: AttachmentCategory) => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [pending, setPending] = useState<PendingImage[]>([]);
  const [uploading, setUploading] = useState<PendingImage[]>([]);
  const queryKey = ["project", pid, "work-items", itemId, "attachments"];

  const attachments = useQuery({
    queryKey,
    queryFn: async () => (await api.get<Attachment[]>(`/projects/${pid}/work-items/${itemId}/attachments`)).data,
    enabled: !!itemId,
  });

  const remove = useMutation({
    mutationFn: (a: Attachment) => api.delete(`/projects/${pid}/work-items/${itemId}/attachments/${a.id}`),
    onSuccess: (_res, a) => {
      if (a.category) onRemoved?.(a.file_name, a.category);
      return qc.invalidateQueries({ queryKey });
    },
    onError: toast.error,
  });

  // Giải phóng object URL của ảnh xem trước khi đóng form
  const previews = useRef(new Set<string>());
  useEffect(() => {
    const urls = previews.current;
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, []);
  const toPending = (file: File, category: AttachmentCategory): PendingImage => {
    const preview = URL.createObjectURL(file);
    previews.current.add(preview);
    return { id: crypto.randomUUID(), file, category, preview };
  };

  /** Thêm ảnh (tải lên nền nếu đã có công việc); trả về tên các ảnh hợp lệ để chèn dấu vào văn bản. */
  function add(files: Iterable<File>, category: AttachmentCategory): string[] {
    const images = pickImages(files, toast.error).map((f) => toPending(f, category));
    if (!images.length) return [];
    if (!itemId) {
      setPending((list) => [...list, ...images]);
    } else {
      setUploading((list) => [...list, ...images]);
      void Promise.all(
        images.map(async (img) => {
          try {
            await uploadImage(pid, itemId, img.file, category);
          } catch (err) {
            toast.error(err);
          } finally {
            setUploading((list) => list.filter((u) => u.id !== img.id));
          }
        }),
      ).then(() => qc.invalidateQueries({ queryKey }));
    }
    return images.map((img) => img.file.name);
  }

  /** Tải các ảnh chọn lúc tạo mới lên công việc vừa tạo; trả về số ảnh lỗi. */
  async function uploadPending(newItemId: number): Promise<number> {
    const results = await Promise.allSettled(
      pending.map((img) => uploadImage(pid, newItemId, img.file, img.category)),
    );
    return results.filter((r) => r.status === "rejected").length;
  }

  function thumbs(category: AttachmentCategory): Thumb[] {
    const saved = (attachments.data ?? [])
      .filter((a) => a.category === category)
      .map<Thumb>((a) => ({
        key: a.id,
        src: a.url,
        name: a.file_name,
        onRemove: canEdit ? () => confirm(`Xoá ảnh ${a.file_name}?`) && remove.mutate(a) : undefined,
      }));
    const local = [...pending, ...uploading]
      .filter((p) => p.category === category)
      .map<Thumb>((p) => ({
        key: p.id,
        src: p.preview,
        name: p.file.name,
        uploading: uploading.includes(p),
        onRemove: itemId
          ? undefined
          : () => {
              setPending((list) => list.filter((x) => x.id !== p.id));
              onRemoved?.(p.file.name, p.category);
            },
      }));
    return [...saved, ...local];
  }

  return { canEdit, add, uploadPending, thumbs };
}

/** Khu "Hình ảnh": hai cột Ảnh lỗi / Ảnh sau khi sửa. */
export function WorkItemImages({ images }: { images: WorkItemImagesState }) {
  const [viewing, setViewing] = useState<Thumb | null>(null);

  return (
    <section className="mt-6">
      <h4 className="mb-2 text-[13px] font-semibold text-ink-2">Hình ảnh</h4>
      <div className="grid gap-4 sm:grid-cols-2">
        {CATEGORIES.map((c) => {
          const list = images.thumbs(c.key);
          return (
            <div key={c.key}>
              <p className="mb-1.5 text-[13px] font-medium text-ink-2">
                {c.label}
                <span className="ml-1.5 font-normal text-ink-3">· {c.hint}</span>
              </p>
              <div className="grid grid-cols-3 gap-2">
                {list.map((t) => (
                  <ImageThumb key={t.key} thumb={t} onOpen={() => setViewing(t)} />
                ))}
                {images.canEdit && <DropZone onFiles={(files) => images.add(files, c.key)} />}
                {!images.canEdit && list.length === 0 && (
                  <p className="col-span-3 text-sm text-ink-3">Chưa có ảnh.</p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {viewing && (
        <Modal open size="xl" title={viewing.name} onClose={() => setViewing(null)}>
          {/* eslint-disable-next-line @next/next/no-img-element -- ảnh từ Cloudflare Images, không qua next/image */}
          <img src={viewing.src} alt={viewing.name} className="mx-auto max-h-[70vh] rounded-lg object-contain" />
          <p className="mt-3 text-center text-sm">
            <a href={viewing.src} target="_blank" rel="noreferrer" className="text-brand hover:underline">
              Mở ảnh gốc trong tab mới
            </a>
          </p>
        </Modal>
      )}
    </section>
  );
}

function ImageThumb({ thumb, onOpen }: { thumb: Thumb; onOpen: () => void }) {
  return (
    <div className="group relative aspect-square overflow-hidden rounded-lg border border-line bg-subtle">
      <button type="button" onClick={onOpen} className="block size-full" aria-label={`Xem ${thumb.name}`}>
        {/* eslint-disable-next-line @next/next/no-img-element -- ảnh từ Cloudflare Images, không qua next/image */}
        <img src={thumb.src} alt={thumb.name} loading="lazy" className="size-full object-cover" />
      </button>
      {thumb.uploading && (
        <div className="absolute inset-0 grid place-items-center bg-surface/60">
          <Loader2 className="size-5 animate-spin text-brand" />
        </div>
      )}
      {thumb.onRemove && !thumb.uploading && (
        <button
          type="button"
          onClick={thumb.onRemove}
          aria-label={`Xoá ${thumb.name}`}
          className="absolute top-1 right-1 rounded-md bg-slate-900/60 p-0.5 text-white opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
        >
          <X className="size-3.5" />
        </button>
      )}
    </div>
  );
}

/** Ô thêm ảnh: bấm để chọn file, kéo thả, hoặc bấm vào rồi Ctrl+V để dán ảnh chụp màn hình. */
function DropZone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => input.current?.click()}
        onPaste={(e) => {
          const files = Array.from(e.clipboardData.files);
          if (files.length) {
            e.preventDefault();
            onFiles(files);
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          onFiles(Array.from(e.dataTransfer.files));
        }}
        title="Bấm để chọn ảnh, kéo thả, hoặc bấm vào ô rồi Ctrl+V để dán ảnh chụp màn hình"
        className={cn(
          "flex aspect-square flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-line-strong",
          "text-xs text-ink-3 transition-colors hover:border-brand hover:text-brand focus:border-brand focus:text-brand",
          over && "border-brand bg-brand-soft text-brand",
        )}
      >
        <ImagePlus className="size-5" />
        <span className="px-1 text-center leading-tight">Thêm / dán ảnh</span>
      </button>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => {
          onFiles(Array.from(e.target.files ?? []));
          e.target.value = "";
        }}
      />
    </>
  );
}
