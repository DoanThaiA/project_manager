"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  File as GenericFile,
  FileArchive,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileX,
  ImageIcon,
  ImageOff,
  Loader2,
  Paperclip,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { Attachment, TextFileFolder } from "@/lib/types";
import { cn } from "@/lib/utils";

export const IMAGE_ACCEPT = "image/png,image/jpeg,image/gif,image/webp";
const MAX_MB = 10;

export const FILE_MAX_MB = 50;

export const PASTE_HINT =
  "Dán ảnh / file (Ctrl+V), kéo thả hoặc bấm \"Gắn ảnh\" / \"Gắn file\"; bấm đúp vào ảnh để phóng to";

/** Ảnh hiển thị trong ô văn bản / khung xem ảnh. */
export type TextImage = { src: string; name: string; uploading?: boolean };

/** File (tài liệu, PDF, Excel...) trong ô văn bản; `name` là tên hiển thị (tên file gốc). */
export type TextFile = { name: string; url?: string; size?: number | null; uploading?: boolean };

/**
 * Nguồn ảnh cho ô văn bản có ảnh: văn bản lưu mỗi ảnh thành một dòng dấu (vd: [Ảnh: tên file]),
 * nguồn ảnh biết dấu nào là ảnh, thêm ảnh mới (trả về các dấu để chèn) và tra ảnh theo dấu.
 * `files`: tương tự cho file (dấu [File: ...]); không có thì ô soạn không cho gắn file.
 */
export type TextImageSource = {
  isMarker: (line: string) => boolean;
  add: (files: File[]) => string[];
  find: (marker: string) => TextImage | undefined;
  files?: {
    isMarker: (line: string) => boolean;
    add: (files: File[]) => string[];
    find: (marker: string) => TextFile | undefined;
  };
};

export function fmtBytes(n?: number | null) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function FileTypeIcon({ name, className }: { name: string; className?: string }) {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const Icon = ["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "heic"].includes(ext)
    ? FileImage
    : ["xls", "xlsx", "csv", "ods"].includes(ext)
      ? FileSpreadsheet
      : ["zip", "rar", "7z", "gz", "tar"].includes(ext)
        ? FileArchive
        : ["pdf", "doc", "docx", "txt", "md", "odt", "ppt", "pptx", "rtf"].includes(ext)
          ? FileText
          : GenericFile;
  return <Icon className={cn("size-4 shrink-0 text-ink-3", className)} />;
}

/** Lọc file đính kèm hợp lệ (không rỗng, không quá FILE_MAX_MB). */
export function pickFiles(files: Iterable<File>, onReject: (msg: string) => void): File[] {
  const ok: File[] = [];
  for (const f of files) {
    if (f.size === 0) onReject(`${f.name}: file rỗng`);
    else if (f.size > FILE_MAX_MB * 1024 * 1024) onReject(`${f.name}: vượt quá ${FILE_MAX_MB} MB`);
    else ok.push(f);
  }
  return ok;
}

/** Lọc file ảnh hợp lệ; ảnh dán từ clipboard thường tên "image.png" nên đặt lại tên theo thời gian. */
export function pickImages(files: Iterable<File>, onReject: (msg: string) => void): File[] {
  const ok: File[] = [];
  const stamp = Date.now();
  for (const f of files) {
    if (!IMAGE_ACCEPT.split(",").includes(f.type)) onReject(`${f.name}: chỉ nhận ảnh PNG, JPEG, GIF, WebP`);
    else if (f.size > MAX_MB * 1024 * 1024) onReject(`${f.name}: vượt quá ${MAX_MB} MB`);
    else if (f.name === "image.png") ok.push(new File([f], `screenshot-${stamp + ok.length}.png`, { type: f.type }));
    else ok.push(f);
  }
  return ok;
}

/** Xem ảnh cỡ lớn. */
export function ImageViewerModal({ image, onClose }: { image: TextImage; onClose: () => void }) {
  return (
    <Modal open size="xl" title={image.name} onClose={onClose}>
      {/* eslint-disable-next-line @next/next/no-img-element -- ảnh từ Cloudflare Images, không qua next/image */}
      <img src={image.src} alt={image.name} className="mx-auto max-h-[70vh] rounded-lg object-contain" />
      {!image.uploading && (
        <p className="mt-3 text-center text-sm">
          <a href={image.src} target="_blank" rel="noreferrer" className="text-brand hover:underline">
            Mở ảnh gốc trong tab mới
          </a>
        </p>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Ảnh dán trong văn bản của dự án (yêu cầu, bình luận, log công việc, sprint...):
// dấu [Ảnh: <tên file>], tên file sinh ngẫu nhiên nên duy nhất trong dự án.
// ---------------------------------------------------------------------------

const INLINE_RE = /^\[Ảnh: ([^\]]+)\]$/;
// File dán trong văn bản: [File: <mã 16 hex>/<tên file gốc>] (lưu trên Cloudflare R2)
const FILE_RE = /^\[File: ([0-9a-f]{16}\/[^\]]+)\]$/;
// Mọi loại dấu ảnh / file, kể cả [Ảnh lỗi: ...] / [Ảnh sau khi sửa: ...] của công việc
const ANY_MARKER_RE = /^\[(Ảnh[^:\]]*|File): [^\]]+\]$/;

export const inlineMarker = (name: string) => `[Ảnh: ${name}]`;
const inlineName = (line: string) => INLINE_RE.exec(line)?.[1];
export const fileMarker = (name: string) => `[File: ${name}]`;
const inlineFileName = (line: string) => FILE_RE.exec(line)?.[1];
/** Tên hiển thị của file dán trong văn bản (bỏ mã ở đầu). */
export const fileDisplayName = (name: string) => name.slice(name.indexOf("/") + 1);

/** Tên các ảnh dán trong văn bản. */
export const inlineImageNames = (text: string | null | undefined) =>
  (text ?? "").split("\n").flatMap((line) => inlineName(line) ?? []);

/** Tên các file dán trong văn bản. */
export const inlineFileNames = (text: string | null | undefined) =>
  (text ?? "").split("\n").flatMap((line) => inlineFileName(line) ?? []);

/** Tên lưu cho file dán trong văn bản: mã ngẫu nhiên + tên gốc (bỏ ký tự làm hỏng dấu [File: ...]). */
function inlineFileRef(file: File) {
  const clean = file.name.replace(/[/\\\]\r\n]/g, "_").trim().slice(0, 200) || "file";
  return `${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}/${clean}`;
}

/** Văn bản bỏ các dòng dấu ảnh / file — để hiện tóm tắt một dòng trong danh sách. */
export const withoutImages = (text: string | null | undefined) =>
  (text ?? "")
    .split("\n")
    .filter((line) => !ANY_MARKER_RE.test(line))
    .join("\n")
    .trim();

const EXT: Record<string, string> = { "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp" };

/**
 * Ảnh / file dán trong văn bản theo tên (URL là URL ký tạm nên luôn hỏi lại máy chủ, không lưu vào văn bản).
 * Kết quả: tên -> bản ghi đính kèm (url, dung lượng...).
 */
function useResolvedImages(pid: number | null | undefined, names: string[], enabled = true) {
  const sorted = useMemo(() => [...new Set(names)].sort(), [names]);
  return useQuery({
    queryKey: ["project", pid, "inline-images", sorted],
    queryFn: async () =>
      (await api.get<Attachment[]>(`/projects/${pid}/inline-images`, { params: { names: sorted } })).data,
    enabled: enabled && !!pid && sorted.length > 0,
    select: (list) => new Map(list.map((a) => [a.file_name, a])),
    placeholderData: keepPreviousData,
    // URL ký tạm hết hạn sau 1 giờ
    staleTime: 10 * 60 * 1000,
    refetchInterval: 30 * 60 * 1000,
  });
}

type Local = { preview: string; url?: string; uploading: boolean };
type LocalFile = { size: number; url?: string; uploading: boolean };

/**
 * Ảnh / file dán trong các ô văn bản của một form. `texts`: giá trị hiện tại của các ô (để tra URL đã lưu).
 * Ảnh (Cloudflare Images) và file (Cloudflare R2) tải lên ngay khi dán; `uploading` > 0 thì chưa nên lưu form.
 * `folder`: ô văn bản thuộc chỗ nào — file lưu vào folder riêng của chỗ đó trên R2 (projects/<id>/text/<folder>/).
 */
export function useInlineImages(pid: number | null | undefined, texts: string[], folder: TextFileFolder) {
  const toast = useToast();
  const [local, setLocal] = useState<Record<string, Local>>({});
  const [localFiles, setLocalFiles] = useState<Record<string, LocalFile>>({});

  // Chỉ hỏi máy chủ những gì đã lưu từ trước; ảnh / file vừa dán đã có URL từ kết quả tải lên
  const joined = texts.join("\n");
  const saved = useMemo(
    () => [
      ...inlineImageNames(joined).filter((n) => !(n in local)),
      ...inlineFileNames(joined).filter((n) => !(n in localFiles)),
    ],
    [joined, local, localFiles],
  );
  const resolved = useResolvedImages(pid, saved);

  const previews = useRef(new Set<string>());
  useEffect(() => {
    const urls = previews.current;
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, []);

  const needProject = () => {
    if (!pid) toast.error("Chọn dự án trước khi gắn ảnh / file");
    return !pid;
  };

  const source: TextImageSource = {
    isMarker: (line) => INLINE_RE.test(line),
    add: (files) => {
      if (needProject()) return [];
      return pickImages(files, toast.error).map((file) => {
        const name = `${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}.${EXT[file.type]}`;
        const preview = URL.createObjectURL(file);
        previews.current.add(preview);
        setLocal((m) => ({ ...m, [name]: { preview, uploading: true } }));
        const body = new FormData();
        body.append("file", new File([file], name, { type: file.type }));
        api
          .post<Attachment>(`/projects/${pid}/inline-images`, body)
          .then((res) => setLocal((m) => ({ ...m, [name]: { preview, url: res.data.url, uploading: false } })))
          .catch((err) => {
            // Bỏ khỏi danh sách: ô văn bản hiện dấu "không có ảnh" để người dùng xoá đi
            toast.error(err);
            setLocal((m) => Object.fromEntries(Object.entries(m).filter(([n]) => n !== name)));
          });
        return inlineMarker(name);
      });
    },
    find: (marker) => {
      const name = inlineName(marker);
      if (!name) return undefined;
      const l = local[name];
      if (l) return { name, src: l.url ?? l.preview, uploading: l.uploading };
      const url = resolved.data?.get(name)?.url;
      return url ? { name, src: url } : undefined;
    },
    files: {
      isMarker: (line) => FILE_RE.test(line),
      add: (files) => {
        if (needProject()) return [];
        return pickFiles(files, toast.error).map((file) => {
          const name = inlineFileRef(file);
          setLocalFiles((m) => ({ ...m, [name]: { size: file.size, uploading: true } }));
          const body = new FormData();
          body.append("file", file);
          body.append("name", name);
          body.append("folder", folder);
          api
            .post<Attachment>(`/projects/${pid}/inline-files`, body)
            .then((res) =>
              setLocalFiles((m) => ({ ...m, [name]: { size: file.size, url: res.data.url, uploading: false } })),
            )
            .catch((err) => {
              toast.error(err);
              setLocalFiles((m) => Object.fromEntries(Object.entries(m).filter(([n]) => n !== name)));
            });
          return fileMarker(name);
        });
      },
      find: (marker) => {
        const name = inlineFileName(marker);
        if (!name) return undefined;
        const l = localFiles[name];
        if (l) return { name: fileDisplayName(name), url: l.url, size: l.size, uploading: l.uploading };
        const a = resolved.data?.get(name);
        return a ? { name: fileDisplayName(name), url: a.url, size: a.size_bytes } : undefined;
      },
    },
  };

  const uploading = [...Object.values(local), ...Object.values(localFiles)].filter((l) => l.uploading).length;
  return { source, uploading };
}

/** Một file trong văn bản: biểu tượng, tên, dung lượng; bấm để tải về. */
export function FileChip({ file, missing, className }: { file?: TextFile; missing?: string; className?: string }) {
  const chip = cn(
    "inline-flex max-w-full items-center gap-1.5 rounded-md border border-line bg-subtle px-2 py-1 text-[13px]",
    className,
  );
  if (!file)
    return (
      <span className={cn(chip, "border-dashed text-ink-3")}>
        <FileX className="size-4 shrink-0" /> <span className="truncate">{missing ?? "Không tìm thấy file"}</span>
      </span>
    );
  const body = (
    <>
      {file.uploading ? (
        <Loader2 className="size-4 shrink-0 animate-spin text-brand" />
      ) : (
        <FileTypeIcon name={file.name} />
      )}
      <span className="truncate font-medium">{file.name}</span>
      {file.size != null && <span className="shrink-0 text-xs text-ink-3">{fmtBytes(file.size)}</span>}
    </>
  );
  return file.url && !file.uploading ? (
    <a
      href={file.url}
      target="_blank"
      rel="noopener noreferrer"
      title={`Tải ${file.name}`}
      className={cn(chip, "text-ink hover:border-brand hover:text-brand")}
    >
      {body}
    </a>
  ) : (
    <span className={chip}>{body}</span>
  );
}

/** Hiển thị văn bản có ảnh / file dán (chỉ đọc); bấm vào ảnh để xem cỡ lớn, bấm file để tải về. */
export function RichText({ pid, text, className }: { pid: number; text: string; className?: string }) {
  const resolved = useResolvedImages(pid, [...inlineImageNames(text), ...inlineFileNames(text)]);
  const [viewing, setViewing] = useState<TextImage | null>(null);
  return (
    <div className={cn("whitespace-pre-line", className)}>
      {text.split("\n").map((line, i) => {
        const fileName = inlineFileName(line);
        if (fileName) {
          const a = resolved.data?.get(fileName);
          const display = fileDisplayName(fileName);
          return (
            <div key={i} className="my-1">
              {a ? (
                <FileChip file={{ name: display, url: a.url, size: a.size_bytes }} />
              ) : resolved.isPending ? (
                <FileChip file={{ name: display, uploading: true }} />
              ) : (
                <FileChip missing={display} />
              )}
            </div>
          );
        }
        const name = inlineName(line);
        if (!name) return <p key={i}>{line || " "}</p>;
        const src = resolved.data?.get(name)?.url;
        return (
          <div key={i} className="my-1.5">
            {src ? (
              <button type="button" onClick={() => setViewing({ name, src })} aria-label={`Xem ảnh ${name}`}>
                {/* eslint-disable-next-line @next/next/no-img-element -- ảnh từ Cloudflare Images, không qua next/image */}
                <img
                  src={src}
                  alt={name}
                  loading="lazy"
                  className="max-h-60 max-w-full cursor-zoom-in rounded-md border border-line"
                />
              </button>
            ) : (
              <ImagePlaceholder loading={resolved.isPending} />
            )}
          </div>
        );
      })}
      {viewing && <ImageViewerModal image={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

/** Nút nhỏ "n ảnh" / "n file" cạnh tóm tắt văn bản trong danh sách; bấm để xem ảnh / tải file. */
export function TextImagesButton({ pid, text }: { pid: number; text: string | null | undefined }) {
  const names = inlineImageNames(text);
  const files = inlineFileNames(text);
  const [open, setOpen] = useState<"images" | "files" | null>(null);
  if (!names.length && !files.length) return null;
  const button = "inline-flex shrink-0 items-center gap-1 rounded-md px-1 text-xs text-brand hover:bg-brand-soft";
  return (
    <>
      {names.length > 0 && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setOpen("images");
          }}
          className={button}
          title="Xem ảnh"
        >
          <ImageIcon className="size-3.5" /> {names.length}
        </button>
      )}
      {files.length > 0 && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setOpen("files");
          }}
          className={button}
          title="Xem file đính kèm"
        >
          <Paperclip className="size-3.5" /> {files.length}
        </button>
      )}
      {open === "images" && <ImageGalleryModal pid={pid} names={names} onClose={() => setOpen(null)} />}
      {open === "files" && <FilesModal pid={pid} names={files} onClose={() => setOpen(null)} />}
    </>
  );
}

function FilesModal({ pid, names, onClose }: { pid: number; names: string[]; onClose: () => void }) {
  const resolved = useResolvedImages(pid, names);
  return (
    <Modal open size="sm" title={`File đính kèm (${names.length})`} onClose={onClose}>
      <ul className="space-y-2">
        {names.map((n) => {
          const a = resolved.data?.get(n);
          const display = fileDisplayName(n);
          return (
            <li key={n}>
              {a ? (
                <FileChip file={{ name: display, url: a.url, size: a.size_bytes }} className="w-full" />
              ) : (
                <FileChip
                  file={resolved.isPending ? { name: display, uploading: true } : undefined}
                  missing={display}
                />
              )}
            </li>
          );
        })}
      </ul>
    </Modal>
  );
}

function ImageGalleryModal({ pid, names, onClose }: { pid: number; names: string[]; onClose: () => void }) {
  const resolved = useResolvedImages(pid, names);
  const [index, setIndex] = useState(0);
  const name = names[index];
  const src = resolved.data?.get(name)?.url;
  return (
    <Modal open size="xl" title={`Ảnh ${index + 1}/${names.length}`} onClose={onClose}>
      <div className="grid min-h-40 place-items-center">
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element -- ảnh từ Cloudflare Images, không qua next/image
          <img src={src} alt={name} className="max-h-[65vh] rounded-lg object-contain" />
        ) : (
          <ImagePlaceholder loading={resolved.isPending} />
        )}
      </div>
      {names.length > 1 && (
        <div className="mt-3 flex flex-wrap justify-center gap-2">
          {names.map((n, i) => {
            const thumb = resolved.data?.get(n)?.url;
            return (
              <button
                key={n}
                type="button"
                onClick={() => setIndex(i)}
                aria-label={`Ảnh ${i + 1}`}
                className={cn(
                  "size-14 overflow-hidden rounded-md border bg-subtle",
                  i === index ? "border-brand ring-2 ring-brand/30" : "border-line",
                )}
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- ảnh từ Cloudflare Images, không qua next/image */}
                {thumb && <img src={thumb} alt="" className="size-full object-cover" />}
              </button>
            );
          })}
        </div>
      )}
      {src && (
        <p className="mt-3 text-center text-sm">
          <a href={src} target="_blank" rel="noreferrer" className="text-brand hover:underline">
            Mở ảnh gốc trong tab mới
          </a>
        </p>
      )}
    </Modal>
  );
}

function ImagePlaceholder({ loading }: { loading: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-line-strong px-2 py-1 text-xs text-ink-3">
      {loading ? <Loader2 className="size-3.5 animate-spin" /> : <ImageOff className="size-3.5" />}
      {loading ? "Đang tải ảnh…" : "Không tìm thấy ảnh"}
    </span>
  );
}
