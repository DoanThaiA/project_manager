"use client";

import { useLayoutEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

const CLAMP = { 1: "line-clamp-1", 2: "line-clamp-2", 3: "line-clamp-3", 4: "line-clamp-4" } as const;

/**
 * Văn bản dài: mặc định hiện tối đa `lines` dòng, nếu bị cắt thì có nút "Xem thêm" / "Thu gọn".
 * Chỉ dùng thẻ span nên đặt được cả bên trong <button> (nút bật/tắt không lan click ra ngoài).
 */
export function ExpandableText({
  text,
  lines = 2,
  className,
}: {
  text: string;
  lines?: keyof typeof CLAMP;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflow, setOverflow] = useState(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || expanded) return;
    const check = () => setOverflow(el.scrollHeight > el.clientHeight + 1);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [text, expanded]);

  const toggle = (e: React.SyntheticEvent) => {
    e.stopPropagation();
    e.preventDefault();
    setExpanded((v) => !v);
  };

  return (
    <span className={cn("block min-w-0", className)}>
      <span ref={ref} className={cn("block break-words whitespace-pre-line", !expanded && CLAMP[lines])}>
        {text}
      </span>
      {(overflow || expanded) && (
        <span
          role="button"
          tabIndex={0}
          aria-expanded={expanded}
          onClick={toggle}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && toggle(e)}
          className="cursor-pointer text-xs font-medium text-brand hover:underline"
        >
          {expanded ? "Thu gọn" : "Xem thêm"}
        </span>
      )}
    </span>
  );
}
