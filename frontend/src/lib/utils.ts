import { clsx, type ClassValue } from "clsx";
import { differenceInCalendarDays, format, formatDistanceToNow, parseISO } from "date-fns";
import { vi } from "date-fns/locale";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const toDate = (v: string | Date) => (typeof v === "string" ? parseISO(v) : v);

export function fmtDate(v?: string | Date | null) {
  return v ? format(toDate(v), "dd/MM/yyyy") : "—";
}

export function fmtDateTime(v?: string | Date | null) {
  return v ? format(toDate(v), "dd/MM/yyyy HH:mm") : "—";
}

export function fmtRelative(v?: string | null) {
  return v ? formatDistanceToNow(parseISO(v), { addSuffix: true, locale: vi }) : "—";
}

export function daysUntil(v?: string | null) {
  return v ? differenceInCalendarDays(parseISO(v), new Date()) : null;
}

/** Decimal từ API trả về dạng chuỗi ("8.00"). */
export function num(v: unknown): number {
  const n = typeof v === "number" ? v : Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
}

export function fmtHours(v: unknown) {
  const n = num(v);
  return `${Number.isInteger(n) ? n : n.toFixed(1)}h`;
}

export function initials(name?: string | null) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return (parts.length > 1 ? parts[parts.length - 2][0] + parts[parts.length - 1][0] : parts[0].slice(0, 2)).toUpperCase();
}

export function todayISO() {
  return format(new Date(), "yyyy-MM-dd");
}
