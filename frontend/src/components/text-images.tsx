"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ImageIcon, ImageOff, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { Attachment } from "@/lib/types";
import { cn } from "@/lib/utils";

export const IMAGE_ACCEPT = "image/png,image/jpeg,image/gif,image/webp";
const MAX_MB = 10;

export const PASTE_HINT = "Dán ảnh (Ctrl+V), kéo thả hoặc bấm \"Gắn ảnh\"; bấm đúp vào ảnh để phóng to";

/** Ảnh hiển thị trong ô văn bản / khung xem ảnh. */
export type TextImage = { src: string; name: string; uploading?: boolean };

/**
 * Nguồn ảnh cho ô văn bản có ảnh: văn bản lưu mỗi ảnh thành một dòng dấu (vd: [Ảnh: tên file]),
 * nguồn ảnh biết dấu nào là ảnh, thêm ảnh mới (trả về các dấu để chèn) và tra ảnh theo dấu.
 */
export type TextImageSource = {
  isMarker: (line: string) => boolean;
  add: (files: File[]) => string[];
  find: (marker: string) => TextImage | undefined;
};

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
// Mọi loại dấu ảnh, kể cả [Ảnh lỗi: ...] / [Ảnh sau khi sửa: ...] của công việc
const ANY_MARKER_RE = /^\[Ảnh[^:\]]*: [^\]]+\]$/;

export const inlineMarker = (name: string) => `[Ảnh: ${name}]`;
const inlineName = (line: string) => INLINE_RE.exec(line)?.[1];

/** Tên các ảnh dán trong văn bản. */
export const inlineImageNames = (text: string | null | undefined) =>
  (text ?? "").split("\n").flatMap((line) => inlineName(line) ?? []);

/** Văn bản bỏ các dòng dấu ảnh — để hiện tóm tắt một dòng trong danh sách. */
export const withoutImages = (text: string | null | undefined) =>
  (text ?? "")
    .split("\n")
    .filter((line) => !ANY_MARKER_RE.test(line))
    .join("\n")
    .trim();

const EXT: Record<string, string> = { "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp" };

/** URL các ảnh theo tên file (URL có thể là URL ký tạm nên luôn hỏi lại máy chủ, không lưu vào văn bản). */
function useResolvedImages(pid: number | null | undefined, names: string[], enabled = true) {
  const sorted = useMemo(() => [...new Set(names)].sort(), [names]);
  return useQuery({
    queryKey: ["project", pid, "inline-images", sorted],
    queryFn: async () =>
      (await api.get<Attachment[]>(`/projects/${pid}/inline-images`, { params: { names: sorted } })).data,
    enabled: enabled && !!pid && sorted.length > 0,
    select: (list) => new Map(list.map((a) => [a.file_name, a.url])),
    placeholderData: keepPreviousData,
    staleTime: 10 * 60 * 1000,
  });
}

type Local = { preview: string; url?: string; uploading: boolean };

/**
 * Ảnh dán trong các ô văn bản của một form. `texts`: giá trị hiện tại của các ô (để tra URL ảnh đã lưu).
 * Ảnh tải lên ngay khi dán; `uploading` > 0 thì chưa nên lưu form.
 */
export function useInlineImages(pid: number | null | undefined, texts: string[]) {
  const toast = useToast();
  const [local, setLocal] = useState<Record<string, Local>>({});

  // Chỉ hỏi máy chủ các ảnh đã lưu từ trước; ảnh vừa dán đã có URL từ kết quả tải lên
  const joined = texts.join("\n");
  const saved = useMemo(() => inlineImageNames(joined).filter((n) => !(n in local)), [joined, local]);
  const resolved = useResolvedImages(pid, saved);

  const previews = useRef(new Set<string>());
  useEffect(() => {
    const urls = previews.current;
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, []);

  const source: TextImageSource = {
    isMarker: (line) => INLINE_RE.test(line),
    add: (files) => {
      if (!pid) {
        toast.error("Chọn dự án trước khi dán ảnh");
        return [];
      }
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
      const url = resolved.data?.get(name);
      return url ? { name, src: url } : undefined;
    },
  };

  const uploading = Object.values(local).filter((l) => l.uploading).length;
  return { source, uploading };
}

/** Hiển thị văn bản có ảnh dán (chỉ đọc); bấm vào ảnh để xem cỡ lớn. */
export function RichText({ pid, text, className }: { pid: number; text: string; className?: string }) {
  const resolved = useResolvedImages(pid, inlineImageNames(text));
  const [viewing, setViewing] = useState<TextImage | null>(null);
  return (
    <div className={cn("whitespace-pre-line", className)}>
      {text.split("\n").map((line, i) => {
        const name = inlineName(line);
        if (!name) return <p key={i}>{line || " "}</p>;
        const src = resolved.data?.get(name);
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

/** Nút nhỏ "n ảnh" cạnh tóm tắt văn bản trong danh sách; bấm để xem các ảnh. */
export function TextImagesButton({ pid, text }: { pid: number; text: string | null | undefined }) {
  const names = inlineImageNames(text);
  const [open, setOpen] = useState(false);
  if (!names.length) return null;
  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        className="inline-flex shrink-0 items-center gap-1 rounded-md px-1 text-xs text-brand hover:bg-brand-soft"
        title="Xem ảnh"
      >
        <ImageIcon className="size-3.5" /> {names.length}
      </button>
      {open && <ImageGalleryModal pid={pid} names={names} onClose={() => setOpen(false)} />}
    </>
  );
}

function ImageGalleryModal({ pid, names, onClose }: { pid: number; names: string[]; onClose: () => void }) {
  const resolved = useResolvedImages(pid, names);
  const [index, setIndex] = useState(0);
  const name = names[index];
  const src = resolved.data?.get(name);
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
            const thumb = resolved.data?.get(n);
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
