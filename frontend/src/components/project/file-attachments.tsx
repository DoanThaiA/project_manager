"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { File as GenericFile, FileArchive, FileImage, FileSpreadsheet, FileText, Loader2, Paperclip, Trash2 } from "lucide-react";
import { useRef, useState } from "react";

import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useMembers } from "@/lib/hooks";
import type { Attachment } from "@/lib/types";
import { cn, fmtDateTime } from "@/lib/utils";

export function fmtBytes(n?: number | null) {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function FileIcon({ name, mime }: { name: string; mime?: string | null }) {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const Icon = mime?.startsWith("image/")
    ? FileImage
    : ["xls", "xlsx", "csv", "ods"].includes(ext)
      ? FileSpreadsheet
      : ["zip", "rar", "7z", "gz", "tar"].includes(ext)
        ? FileArchive
        : ["pdf", "doc", "docx", "txt", "md", "odt", "ppt", "pptx"].includes(ext)
          ? FileText
          : GenericFile;
  return <Icon className="size-4 shrink-0 text-ink-3" />;
}

type Uploading = { id: string; name: string; size: number; percent: number };

/**
 * File đính kèm (tài liệu, PDF, Excel, zip...) lưu trên MinIO, cho bản ghi có endpoint `${base}/files`
 * (vd `/projects/1/work-items/5`). Link tải là URL ký tạm nên danh sách được tải lại định kỳ.
 */
export function FileAttachments({ pid, base, canEdit }: { pid: number; base: string; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { byId } = useMembers(pid);
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [uploading, setUploading] = useState<Uploading[]>([]);
  const queryKey = ["project", pid, "files", base];

  const files = useQuery({
    queryKey,
    queryFn: async () => (await api.get<Attachment[]>(`${base}/files`)).data,
    refetchInterval: 15 * 60 * 1000,
  });

  const remove = useMutation({
    mutationFn: (f: Attachment) => api.delete(`${base}/files/${f.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
    onError: toast.error,
  });

  function upload(list: File[]) {
    if (!list.length) return;
    const items = list.map((file) => ({ file, row: { id: crypto.randomUUID(), name: file.name, size: file.size, percent: 0 } }));
    setUploading((u) => [...u, ...items.map((i) => i.row)]);
    void Promise.all(
      items.map(async ({ file, row }) => {
        const body = new FormData();
        body.append("file", file);
        try {
          await api.post<Attachment>(`${base}/files`, body, {
            onUploadProgress: (e) => {
              const percent = e.total ? Math.round((e.loaded / e.total) * 100) : 0;
              setUploading((u) => u.map((x) => (x.id === row.id ? { ...x, percent } : x)));
            },
          });
        } catch (err) {
          toast.error(err);
        } finally {
          setUploading((u) => u.filter((x) => x.id !== row.id));
        }
      }),
    ).then(() => qc.invalidateQueries({ queryKey }));
  }

  const saved = files.data ?? [];
  const empty = !saved.length && !uploading.length;

  return (
    <div>
      {files.isPending ? (
        <p className="py-2 text-sm text-ink-3">Đang tải…</p>
      ) : empty && !canEdit ? (
        <p className="py-2 text-sm text-ink-3">Chưa có file đính kèm.</p>
      ) : (
        !empty && (
          <ul className="divide-y divide-line rounded-lg border border-line">
            {saved.map((f) => (
              <li key={f.id} className="group flex items-center gap-3 px-3 py-2 text-sm">
                <FileIcon name={f.file_name} mime={f.mime_type} />
                <div className="min-w-0 flex-1">
                  <a
                    href={f.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block truncate font-medium text-ink hover:text-brand hover:underline"
                    title={`Tải ${f.file_name}`}
                  >
                    {f.file_name}
                  </a>
                  <p className="text-xs text-ink-3">
                    {fmtBytes(f.size_bytes)} ·{" "}
                    {(f.uploaded_by && byId.get(f.uploaded_by)?.full_name) ?? "—"} · {fmtDateTime(f.created_at)}
                  </p>
                </div>
                {canEdit && (
                  <button
                    type="button"
                    aria-label={`Xoá ${f.file_name}`}
                    disabled={remove.isPending && remove.variables?.id === f.id}
                    onClick={() => confirm(`Xoá file ${f.file_name}?`) && remove.mutate(f)}
                    className="rounded-md p-1 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-danger-soft hover:text-danger focus:opacity-100"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                )}
              </li>
            ))}
            {uploading.map((u) => (
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

      {canEdit && (
        <>
          <button
            type="button"
            onClick={() => input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              upload(Array.from(e.dataTransfer.files));
            }}
            className={cn(
              "mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-line-strong px-3 py-2.5",
              "text-[13px] text-ink-3 transition-colors hover:border-brand hover:text-brand focus:border-brand focus:text-brand",
              over && "border-brand bg-brand-soft text-brand",
            )}
          >
            <Paperclip className="size-4" />
            Chọn hoặc kéo thả file (tài liệu, PDF, Excel, zip…)
          </button>
          <input
            ref={input}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              upload(Array.from(e.target.files ?? []));
              e.target.value = "";
            }}
          />
        </>
      )}
    </div>
  );
}
