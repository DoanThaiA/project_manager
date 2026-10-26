"use client";

import { mergeAttributes, Node } from "@tiptap/core";
import Document from "@tiptap/extension-document";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import { Dropcursor, Gapcursor, Placeholder, UndoRedo } from "@tiptap/extensions";
import type { Node as PMNode } from "@tiptap/pm/model";
import {
  type Editor,
  EditorContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  type ReactNodeViewProps,
  useEditor,
} from "@tiptap/react";
import { Download, ImageOff, ImagePlus, Loader2, Paperclip, ZoomIn } from "lucide-react";
import { createContext, useContext, useEffect, useRef, useState } from "react";

import {
  FileChip,
  IMAGE_ACCEPT,
  ImageViewerModal,
  type TextImage,
  type TextImageSource,
} from "@/components/text-images";
import { cn } from "@/lib/utils";

// Node view render qua portal bên trong EditorContent nên đọc được context này
const ImagesContext = createContext<{
  source: TextImageSource;
  view: (image: TextImage) => void;
} | null>(null);

function ImageView({ node, editor }: ReactNodeViewProps) {
  const ctx = useContext(ImagesContext);
  const marker = node.attrs.marker as string;
  const image = ctx?.source.find(marker);
  const view = () => image && ctx?.view(image);
  return (
    <NodeViewWrapper className="my-1.5" data-drag-handle>
      {image ? (
        <span className="group relative inline-block">
          {/* eslint-disable-next-line @next/next/no-img-element -- ảnh từ Cloudflare Images, không qua next/image */}
          <img
            src={image.src}
            alt={image.name}
            title={editor.isEditable ? `${image.name} — bấm đúp để phóng to` : image.name}
            // Đang soạn: bấm một lần để chọn ảnh (xoá / kéo thả), bấm đúp để xem; chỉ đọc: bấm để xem
            onClick={editor.isEditable ? undefined : view}
            onDoubleClick={view}
            className={cn("max-h-60 max-w-full rounded-md border border-line", !editor.isEditable && "cursor-zoom-in")}
          />
          {image.uploading ? (
            <span className="absolute inset-0 grid place-items-center rounded-md bg-surface/60">
              <Loader2 className="size-5 animate-spin text-brand" />
            </span>
          ) : (
            editor.isEditable && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  view();
                }}
                aria-label={`Xem ảnh ${image.name}`}
                className="absolute top-1 right-1 rounded-md bg-slate-900/60 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
              >
                <ZoomIn className="size-3.5" />
              </button>
            )
          )}
        </span>
      ) : (
        <span className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-line-strong px-2 py-1 text-xs text-ink-3">
          <ImageOff className="size-3.5" /> {marker}
        </span>
      )}
    </NodeViewWrapper>
  );
}

/** Ảnh trong văn bản: khối riêng, lưu xuống thành một dòng dấu ảnh (vd: [Ảnh: tên file]). */
const InlineImage = Node.create({
  name: "textImage",
  group: "block",
  atom: true,
  draggable: true,
  addAttributes: () => ({ marker: { default: "" } }),
  renderHTML: ({ HTMLAttributes }) => ["div", mergeAttributes(HTMLAttributes, { "data-text-image": "" })],
  addNodeView: () => ReactNodeViewRenderer(ImageView),
});

function FileView({ node, editor }: ReactNodeViewProps) {
  const ctx = useContext(ImagesContext);
  const marker = node.attrs.marker as string;
  const file = ctx?.source.files?.find(marker);
  if (!editor.isEditable || !file?.url) {
    return (
      <NodeViewWrapper className="my-1" data-drag-handle>
        <FileChip file={file} missing={marker} />
      </NodeViewWrapper>
    );
  }
  // Đang soạn: bấm để chọn file (xoá / kéo thả), nút tải riêng bên cạnh
  return (
    <NodeViewWrapper className="my-1" data-drag-handle>
      <span className="inline-flex max-w-full items-center gap-1">
        <FileChip file={{ ...file, url: undefined }} />
        <a
          href={file.url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Tải ${file.name}`}
          className="rounded-md p-1 text-ink-3 hover:bg-subtle hover:text-brand"
        >
          <Download className="size-3.5" />
        </a>
      </span>
    </NodeViewWrapper>
  );
}

/** File trong văn bản: khối riêng, lưu xuống thành một dòng dấu file (vd: [File: mã/tên file]). */
const InlineFile = Node.create({
  name: "textFile",
  group: "block",
  atom: true,
  draggable: true,
  addAttributes: () => ({ marker: { default: "" } }),
  renderHTML: ({ HTMLAttributes }) => ["div", mergeAttributes(HTMLAttributes, { "data-text-file": "" })],
  addNodeView: () => ReactNodeViewRenderer(FileView),
});

/** Văn bản thuần (mỗi dòng một đoạn, dòng dấu ảnh / file thành ảnh / file) -> nội dung editor. */
function toDoc(text: string, source: TextImageSource) {
  return {
    type: "doc",
    content: text.split("\n").map((line) => {
      if (source.isMarker(line)) return { type: InlineImage.name, attrs: { marker: line } };
      if (source.files?.isMarker(line)) return { type: InlineFile.name, attrs: { marker: line } };
      return {
        type: "paragraph",
        content: line ? [{ type: "text", text: line }] : [],
      };
    }),
  };
}

function toText(doc: PMNode): string {
  const lines: string[] = [];
  const markers = new Set([InlineImage.name, InlineFile.name]);
  doc.forEach((node) => lines.push(markers.has(node.type.name) ? node.attrs.marker : node.textContent));
  return lines.join("\n");
}

/**
 * Tách file trong clipboard / kéo vào thành ảnh và file khác. Có kèm chữ (copy từ Word, web...) thì dán chữ.
 */
function droppedFiles(data: DataTransfer | null): { images: File[]; others: File[] } {
  if (!data || data.getData("text/plain")) return { images: [], others: [] };
  const all = Array.from(data.files);
  return { images: all.filter((f) => f.type.startsWith("image/")), others: all.filter((f) => !f.type.startsWith("image/")) };
}

/**
 * Ô văn bản hiển thị ảnh ngay trong nội dung. Dán (Ctrl+V) / kéo thả ảnh: giao cho `source` thêm ảnh
 * và chèn ảnh tại con trỏ. Giá trị vẫn là văn bản thuần (dấu ảnh mỗi dòng).
 */
export function ImageTextEditor({
  id,
  value,
  onChange,
  source,
  editable = true,
  rows = 3,
  placeholder,
  autoFocus,
  onSubmit,
  "aria-label": ariaLabel,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  source: TextImageSource;
  editable?: boolean;
  rows?: number;
  placeholder?: string;
  autoFocus?: boolean;
  /** Ctrl/⌘ + Enter */
  onSubmit?: () => void;
  "aria-label"?: string;
}) {
  // editorProps / onUpdate chỉ gắn một lần lúc tạo editor -> đọc giá trị mới nhất qua ref
  const latest = useRef({ onChange, source, onSubmit });
  useEffect(() => {
    latest.current = { onChange, source, onSubmit };
  });

  const editorRef = useRef<Editor | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const attachInput = useRef<HTMLInputElement>(null);
  const [viewing, setViewing] = useState<TextImage | null>(null);

  /** Thêm ảnh / file qua `source` và chèn vào văn bản tại `pos` (mặc định: con trỏ). */
  const insertImages = (files: File[], pos?: number, kind: "image" | "file" = "image") => {
    const { source } = latest.current;
    const markers = kind === "image" ? source.add(files) : (source.files?.add(files) ?? []);
    const editor = editorRef.current;
    if (!markers.length || !editor) return;
    const content = markers.map((marker) => ({
      type: kind === "image" ? InlineImage.name : InlineFile.name,
      attrs: { marker },
    }));
    const chain = editor.chain().focus();
    (pos === undefined ? chain.insertContent(content) : chain.insertContentAt(pos, content)).run();

    // Sau khi chèn, ảnh đang được chọn -> gõ tiếp sẽ thay mất ảnh. Đưa con trỏ xuống dòng chữ ngay sau ảnh.
    const after = editor.state.selection.to;
    if (editor.state.doc.nodeAt(after)?.type.name !== "paragraph") {
      editor.chain().insertContentAt(after, { type: "paragraph" }).run();
    }
    editor.commands.setTextSelection(after + 1);
  };

  const editor = useEditor({
    immediatelyRender: false, // Next.js: tránh lệch HTML giữa server và client
    editable,
    autofocus: autoFocus ? "end" : false,
    extensions: [
      Document,
      Paragraph,
      Text,
      UndoRedo,
      Dropcursor,
      Gapcursor,
      InlineImage,
      InlineFile,
      Placeholder.configure({ placeholder: placeholder ?? "" }),
    ],
    content: toDoc(value, source),
    editorProps: {
      attributes: {
        ...(id ? { id } : {}),
        ...(ariaLabel ? { "aria-label": ariaLabel } : {}),
        role: "textbox",
        "aria-multiline": "true",
        class: "outline-none",
        style: `min-height: ${rows * 1.625}em`,
      },
      handleKeyDown: (_view, event) => {
        const { onSubmit } = latest.current;
        if (!onSubmit || event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return false;
        onSubmit();
        return true;
      },
      handlePaste: (view, event) => {
        const { images, others } = droppedFiles(event.clipboardData);
        const files = latest.current.source.files ? others : [];
        if (!view.editable || (!images.length && !files.length)) return false;
        if (images.length) insertImages(images);
        if (files.length) insertImages(files, undefined, "file");
        return true;
      },
      handleDrop: (view, event, _slice, moved) => {
        const { images, others } = moved ? { images: [], others: [] } : droppedFiles(event.dataTransfer);
        const files = latest.current.source.files ? others : [];
        if (!view.editable || (!images.length && !files.length)) return false;
        const pos = view.posAtCoords({
          left: event.clientX,
          top: event.clientY,
        })?.pos;
        if (images.length) insertImages(images, pos);
        if (files.length) insertImages(files, images.length ? undefined : pos, "file");
        return true;
      },
    },
    onUpdate: ({ editor }) => latest.current.onChange(toText(editor.state.doc)),
  });

  useEffect(() => {
    editorRef.current = editor;
  }, [editor]);

  // Giá trị đổi từ bên ngoài (vd: xoá ảnh ở khu Hình ảnh -> bỏ dấu) thì nạp lại nội dung
  useEffect(() => {
    if (editor && toText(editor.state.doc) !== value) {
      editor.commands.setContent(toDoc(value, latest.current.source), {
        emitUpdate: false,
      });
    }
  }, [editor, value]);

  useEffect(() => {
    editor?.setEditable(editable);
  }, [editor, editable]);

  return (
    <ImagesContext.Provider value={{ source, view: setViewing }}>
      <div
        className={cn(
          "w-full overflow-hidden rounded-lg border border-line-strong bg-surface transition-colors",
          "focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20",
          !editable && "bg-subtle",
        )}
      >
        <EditorContent
          editor={editor}
          className={cn(
            "max-h-[50vh] w-full cursor-text overflow-y-auto px-3 py-2",
            "text-sm leading-relaxed text-ink",
            // Viền ảnh đang chọn chỉ hiện khi đang soạn (ProseMirror giữ selection cả khi mất focus)
            "[&_.ProseMirror-focused_.ProseMirror-selectednode_:is(img,span)]:ring-2 [&_.ProseMirror-focused_.ProseMirror-selectednode_:is(img,span)]:ring-brand",
            // Chữ gợi ý khi ô trống (Placeholder gắn data-placeholder + class is-editor-empty vào đoạn đầu)
            "[&_p.is-editor-empty:first-child]:before:pointer-events-none [&_p.is-editor-empty:first-child]:before:float-left [&_p.is-editor-empty:first-child]:before:h-0 [&_p.is-editor-empty:first-child]:before:text-ink-3 [&_p.is-editor-empty:first-child]:before:content-[attr(data-placeholder)]",
            !editable && "cursor-default text-ink-3",
          )}
          onClick={() => editor?.commands.focus()}
        />
        {editable && (
          <div className="flex border-t border-line px-1.5 py-1">
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-ink-3 transition-colors hover:bg-subtle hover:text-brand"
            >
              <ImagePlus className="size-3.5" /> Gắn ảnh
            </button>
            <input
              ref={fileInput}
              type="file"
              accept={IMAGE_ACCEPT}
              multiple
              hidden
              onChange={(e) => {
                // Chèn tại vị trí con trỏ cuối cùng trong ô (ProseMirror giữ selection khi mất focus)
                insertImages(Array.from(e.target.files ?? []));
                e.target.value = "";
              }}
            />
            {source.files && (
              <>
                <button
                  type="button"
                  onClick={() => attachInput.current?.click()}
                  className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-ink-3 transition-colors hover:bg-subtle hover:text-brand"
                >
                  <Paperclip className="size-3.5" /> Gắn file
                </button>
                <input
                  ref={attachInput}
                  type="file"
                  multiple
                  hidden
                  onChange={(e) => {
                    insertImages(Array.from(e.target.files ?? []), undefined, "file");
                    e.target.value = "";
                  }}
                />
              </>
            )}
          </div>
        )}
      </div>
      {viewing && <ImageViewerModal image={viewing} onClose={() => setViewing(null)} />}
    </ImagesContext.Provider>
  );
}
