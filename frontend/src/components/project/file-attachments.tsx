"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, Loader2, Paperclip, Trash2, X } from "lucide-react";
import { useRef, useState } from "react";

import { FilePreviewModal, type PreviewFile } from "@/components/file-preview";
import { fmtBytes, FileTypeIcon, pickFiles } from "@/components/text-images";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useMembers } from "@/lib/hooks";
import type { Attachment } from "@/lib/types";
import { cn, fmtDateTime } from "@/lib/utils";

/** File chọn khi đang tạo mới — tải lên sau khi bản ghi được tạo. */
type PendingFile = { id: string; file: File };
type Uploading = { id: string; name: string; size: number; percent: number };

async function uploadFile(base: string, file: File, onProgress?: (percent: number) => void) {
  const body = new FormData();
  body.append("file", file);
  return (
    await api.post<Attachment>(`${base}/files`, body, {
      onUploadProgress: (e) => onProgress?.(e.total ? Math.round((e.loaded / e.total) * 100) : 0),
    })
  ).data;
}

export type FileAttachmentsState = ReturnType<typeof useFileAttachments>;

/**
 * File đính kèm (tài liệu, PDF, Excel, zip...) lưu trên Cloudflare R2, cho bản ghi có endpoint `${base}/files`
 * (vd `/projects/1/work-items/5`). Có `base`: tải thẳng lên ngay; chưa có (form tạo mới): giữ trong `pending`,
 * gọi uploadPending sau khi tạo bản ghi. Link tải là URL ký tạm nên danh sách được tải lại định kỳ.
 */
export function useFileAttachments({ pid, base, canEdit }: { pid: number; base?: string; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [pending, setPending] = useState<PendingFile[]>([]);
  const [uploading, setUploading] = useState<Uploading[]>([]);
  const queryKey = ["project", pid, "files", base];

  const saved = useQuery({
    queryKey,
    queryFn: async () => (await api.get<Attachment[]>(`${base}/files`)).data,
    enabled: !!base,
    refetchInterval: 15 * 60 * 1000,
  });

  const remove = useMutation({
    mutationFn: (f: Attachment) => api.delete(`${base}/files/${f.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
    onError: toast.error,
  });

  function add(list: Iterable<File>) {
    const files = pickFiles(list, toast.error);
    if (!files.length) return;
    if (!base) {
      setPending((p) => [...p, ...files.map((file) => ({ id: crypto.randomUUID(), file }))]);
      return;
    }
    const rows = files.map((file) => ({ file, row: { id: crypto.randomUUID(), name: file.name, size: file.size, percent: 0 } }));
    setUploading((u) => [...u, ...rows.map((r) => r.row)]);
    void Promise.all(
      rows.map(async ({ file, row }) => {
        try {
          await uploadFile(base, file, (percent) =>
            setUploading((u) => u.map((x) => (x.id === row.id ? { ...x, percent } : x))),
          );
        } catch (err) {
          toast.error(err);
        } finally {
          setUploading((u) => u.filter((x) => x.id !== row.id));
        }
      }),
    ).then(() => qc.invalidateQueries({ queryKey }));
  }

  /** Tải các file chọn lúc tạo mới lên bản ghi vừa tạo; trả về số file lỗi. */
  async function uploadPending(newBase: string): Promise<number> {
    const results = await Promise.allSettled(pending.map((p) => uploadFile(newBase, p.file)));
    return results.filter((r) => r.status === "rejected").length;
  }

  const removePending = (id: string) => setPending((p) => p.filter((x) => x.id !== id));

  return { pid, canEdit, saved, pending, uploading, add, remove, removePending, uploadPending };
}

/** Khu "File đính kèm": danh sách file + ô chọn / kéo thả file. */
export function FileAttachments({ files }: { files: FileAttachmentsState }) {
  const { byId } = useMembers(files.pid);
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [previewing, setPreviewing] = useState<PreviewFile | null>(null);
  const saved = files.saved.data ?? [];
  const previewOf = (f: Attachment): PreviewFile | null =>
    f.preview_kind && f.preview_url
      ? { name: f.file_name, url: f.url, previewKind: f.preview_kind, previewUrl: f.preview_url }
      : null;
  const iconButton = "rounded-md p-1 text-ink-3 hover:bg-subtle hover:text-brand";
  const empty = !saved.length && !files.pending.length && !files.uploading.length;

  return (
    <div>
      {files.saved.isLoading ? (
        <p className="py-2 text-sm text-ink-3">Đang tải…</p>
      ) : empty && !files.canEdit ? (
        <p className="py-2 text-sm text-ink-3">Chưa có file đính kèm.</p>
      ) : (
        !empty && (
          <ul className="divide-y divide-line rounded-lg border border-line">
            {saved.map((f) => {
              const preview = previewOf(f);
              return (
                <li key={f.id} className="group flex items-center gap-3 px-3 py-2 text-sm">
                  <FileTypeIcon name={f.file_name} />
                  <div className="min-w-0 flex-1">
                    {/* Bấm tên: xem ngay nếu loại file xem được, không thì tải về */}
                    {preview ? (
                      <button
                        type="button"
                        onClick={() => setPreviewing(preview)}
                        className="block max-w-full truncate text-left font-medium text-ink hover:text-brand hover:underline"
                        title={`Xem ${f.file_name}`}
                      >
                        {f.file_name}
                      </button>
                    ) : (
                      <a
                        href={f.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block truncate font-medium text-ink hover:text-brand hover:underline"
                        title={`Tải ${f.file_name}`}
                      >
                        {f.file_name}
                      </a>
                    )}
                    <p className="text-xs text-ink-3">
                      {fmtBytes(f.size_bytes)} ·{" "}
                      {(f.uploaded_by && byId.get(f.uploaded_by)?.full_name) ?? "—"} · {fmtDateTime(f.created_at)}
                    </p>
                  </div>
                  {preview && (
                    <button type="button" aria-label={`Xem ${f.file_name}`} onClick={() => setPreviewing(preview)} className={iconButton}>
                      <Eye className="size-3.5" />
                    </button>
                  )}
                  <a href={f.url} target="_blank" rel="noopener noreferrer" aria-label={`Tải ${f.file_name}`} className={iconButton}>
                    <Download className="size-3.5" />
                  </a>
                  {files.canEdit && (
                    <button
                      type="button"
                      aria-label={`Xoá ${f.file_name}`}
                      disabled={files.remove.isPending && files.remove.variables?.id === f.id}
                      onClick={() => confirm(`Xoá file ${f.file_name}?`) && files.remove.mutate(f)}
                      className="rounded-md p-1 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-danger-soft hover:text-danger focus:opacity-100"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  )}
                </li>
              );
            })}
            {files.pending.map((p) => (
              <li key={p.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                <FileTypeIcon name={p.file.name} />
                <span className="min-w-0 flex-1 truncate">{p.file.name}</span>
                <span className="text-xs text-ink-3">{fmtBytes(p.file.size)} · tải lên khi lưu</span>
                <button
                  type="button"
                  aria-label={`Bỏ ${p.file.name}`}
                  onClick={() => files.removePending(p.id)}
                  className="rounded-md p-1 text-ink-3 hover:bg-subtle hover:text-ink"
                >
                  <X className="size-3.5" />
                </button>
              </li>
            ))}
            {files.uploading.map((u) => (
              <li key={u.id} className="flex items-center gap-3 px-3 py-2 text-sm text-ink-3">
                <Loader2 className="size-4 shrink-0 animate-spin text-brand" />
                <span className="min-w-0 flex-1 truncate">{u.name}</span>
                <span className="text-xs tabular-nums">
                  {fmtBytes(u.size)} · {u.percent}%
                </span>
              </li>
            ))}
          </ul>
        )
      )}

      {files.canEdit && (
        <>
          <button
            type="button"
            onClick={() => input.current?.click()}
            onPaste={(e) => {
              const pasted = Array.from(e.clipboardData.files);
              if (pasted.length) {
                e.preventDefault();
                files.add(pasted);
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
              files.add(Array.from(e.dataTransfer.files));
            }}
            className={cn(
              "mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-line-strong px-3 py-2.5",
              "text-[13px] text-ink-3 transition-colors hover:border-brand hover:text-brand focus:border-brand focus:text-brand",
              over && "border-brand bg-brand-soft text-brand",
            )}
          >
            <Paperclip className="size-4" />
            Chọn, kéo thả hoặc dán file (tài liệu, PDF, Excel, zip…)
          </button>
          <input
            ref={input}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              files.add(Array.from(e.target.files ?? []));
              e.target.value = "";
            }}
          />
        </>
      )}
      {previewing && <FilePreviewModal file={previewing} onClose={() => setPreviewing(null)} />}
    </div>
  );
}
