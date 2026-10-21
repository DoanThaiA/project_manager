"use client";

import { mergeAttributes, Node } from "@tiptap/core";
import Document from "@tiptap/extension-document";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import { Dropcursor, Gapcursor, UndoRedo } from "@tiptap/extensions";
import type { Node as PMNode } from "@tiptap/pm/model";
import {
  type Editor,
  EditorContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  type ReactNodeViewProps,
  useEditor,
} from "@tiptap/react";
import { ImageOff, Loader2 } from "lucide-react";
import { createContext, useContext, useEffect, useRef } from "react";

import {
  imageMarker,
  parseImageMarker,
  type WorkItemImagesState,
} from "@/components/project/work-item-images";
import type { AttachmentCategory } from "@/lib/types";
import { cn } from "@/lib/utils";

// Node view render qua portal bên trong EditorContent nên đọc được context này
const ImagesContext = createContext<WorkItemImagesState | null>(null);

function ImageView({ node }: ReactNodeViewProps) {
  const images = useContext(ImagesContext);
  const { category, name } = node.attrs as { category: AttachmentCategory; name: string };
  const thumb = images?.find(category, name);
  return (
    <NodeViewWrapper className="my-1.5" data-drag-handle>
      {thumb ? (
        <span className="relative inline-block">
          {/* eslint-disable-next-line @next/next/no-img-element -- ảnh từ Cloudflare Images, không qua next/image */}
          <img
            src={thumb.src}
            alt={name}
            title={name}
            className="max-h-60 max-w-full rounded-md border border-line"
          />
          {thumb.uploading && (
            <span className="absolute inset-0 grid place-items-center rounded-md bg-surface/60">
              <Loader2 className="size-5 animate-spin text-brand" />
            </span>
          )}
        </span>
      ) : (
        <span className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-line-strong px-2 py-1 text-xs text-ink-3">
          <ImageOff className="size-3.5" /> {imageMarker(category, name)}
        </span>
      )}
    </NodeViewWrapper>
  );
}

/** Ảnh trong văn bản: khối riêng, lưu xuống thành một dòng dấu [Ảnh lỗi: tên file]. */
const InlineImage = Node.create({
  name: "workItemImage",
  group: "block",
  atom: true,
  draggable: true,
  addAttributes: () => ({ category: { default: "bug" }, name: { default: "" } }),
  renderHTML: ({ HTMLAttributes }) => ["div", mergeAttributes(HTMLAttributes, { "data-work-item-image": "" })],
  addNodeView: () => ReactNodeViewRenderer(ImageView),
});

/** Văn bản thuần (mỗi dòng một đoạn, dòng dấu ảnh thành ảnh) -> nội dung editor. */
function toDoc(text: string) {
  return {
    type: "doc",
    content: text.split("\n").map((line) => {
      const img = parseImageMarker(line);
      if (img) return { type: InlineImage.name, attrs: img };
      return { type: "paragraph", content: line ? [{ type: "text", text: line }] : [] };
    }),
  };
}

function toText(doc: PMNode): string {
  const lines: string[] = [];
  doc.forEach((node) =>
    lines.push(node.type.name === InlineImage.name ? imageMarker(node.attrs.category, node.attrs.name) : node.textContent),
  );
  return lines.join("\n");
}

/** Chỉ lấy ảnh khi clipboard / file kéo vào chỉ có ảnh; có kèm chữ (copy từ Word, web...) thì dán chữ. */
function imageFiles(data: DataTransfer | null): File[] {
  if (!data || data.getData("text/plain")) return [];
  return Array.from(data.files).filter((f) => f.type.startsWith("image/"));
}

/**
 * Ô văn bản hiển thị ảnh ngay trong nội dung. Dán (Ctrl+V) / kéo thả ảnh: thêm vào nhóm ảnh `category`
 * của công việc và chèn ảnh tại con trỏ. Giá trị vẫn là văn bản thuần (dấu ảnh mỗi dòng).
 */
export function ImageTextEditor({
  id,
  value,
  onChange,
  category,
  images,
  editable,
  rows = 3,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  category: AttachmentCategory;
  images: WorkItemImagesState;
  editable: boolean;
  rows?: number;
}) {
  // editorProps / onUpdate chỉ gắn một lần lúc tạo editor -> đọc giá trị mới nhất qua ref
  const latest = useRef({ onChange, images, category });
  useEffect(() => {
    latest.current = { onChange, images, category };
  });

  const editorRef = useRef<Editor | null>(null);

  /** Thêm ảnh vào nhóm ảnh của công việc và chèn vào văn bản tại `pos` (mặc định: con trỏ). */
  const insertImages = (files: File[], pos?: number) => {
    const { images, category } = latest.current;
    const names = images.add(files, category);
    const editor = editorRef.current;
    if (!names.length || !editor) return;
    const content = names.map((name) => ({ type: InlineImage.name, attrs: { category, name } }));
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
    extensions: [Document, Paragraph, Text, UndoRedo, Dropcursor, Gapcursor, InlineImage],
    content: toDoc(value),
    editorProps: {
      attributes: {
        id,
        role: "textbox",
        "aria-multiline": "true",
        class: "outline-none",
        style: `min-height: ${rows * 1.625}em`,
      },
      handlePaste: (view, event) => {
        const files = imageFiles(event.clipboardData);
        if (!view.editable || !files.length) return false;
        insertImages(files);
        return true;
      },
      handleDrop: (view, event, _slice, moved) => {
        const files = moved ? [] : imageFiles(event.dataTransfer);
        if (!view.editable || !files.length) return false;
        const pos = view.posAtCoords({ left: event.clientX, top: event.clientY })?.pos;
        insertImages(files, pos);
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
    if (editor && toText(editor.state.doc) !== value) editor.commands.setContent(toDoc(value), { emitUpdate: false });
  }, [editor, value]);

  useEffect(() => {
    editor?.setEditable(editable);
  }, [editor, editable]);

  return (
    <ImagesContext.Provider value={images}>
      <EditorContent
        editor={editor}
        className={cn(
          "max-h-[50vh] w-full cursor-text overflow-y-auto rounded-lg border border-line-strong bg-surface px-3 py-2",
          "text-sm leading-relaxed text-ink transition-colors",
          "focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20",
          // Viền ảnh đang chọn chỉ hiện khi đang soạn (ProseMirror giữ selection cả khi mất focus)
          "[&_.ProseMirror-focused_.ProseMirror-selectednode_:is(img,span)]:ring-2 [&_.ProseMirror-focused_.ProseMirror-selectednode_:is(img,span)]:ring-brand",
          !editable && "cursor-default bg-subtle text-ink-3",
        )}
        onClick={() => editor?.commands.focus()}
      />
    </ImagesContext.Provider>
  );
}
