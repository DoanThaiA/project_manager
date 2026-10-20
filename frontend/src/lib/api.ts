import axios, { AxiosError } from "axios";

const TOKEN_KEY = "pm_token";
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((fn) => fn());

/** Token JWT trong localStorage, có subscribe để dùng với useSyncExternalStore. */
export const tokenStore = {
  subscribe(fn: () => void) {
    listeners.add(fn);
    window.addEventListener("storage", fn); // đăng xuất ở tab khác
    return () => {
      listeners.delete(fn);
      window.removeEventListener("storage", fn);
    };
  },
  get(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string) {
    localStorage.setItem(TOKEN_KEY, token);
    notify();
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
    notify();
  },
};

// Gọi qua rewrite /api -> backend (next.config.ts), không cần CORS
// paramsSerializer: mảng -> ?status=a&status=b (định dạng FastAPI)
export const api = axios.create({ baseURL: "/api/v1", paramsSerializer: { indexes: null } });

api.interceptors.request.use((config) => {
  const token = tokenStore.get();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (error: AxiosError) => {
    // Token hết hạn: xoá token, AppShell sẽ tự chuyển về /login
    if (error.response?.status === 401 && !error.config?.url?.includes("/auth/login")) tokenStore.clear();
    return Promise.reject(error);
  },
);

/** Thông báo lỗi dễ đọc từ phản hồi FastAPI. */
export function errorMessage(error: unknown): string {
  if (error instanceof AxiosError) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail
        .map((d: { loc?: (string | number)[]; msg?: string }) => {
          const field = d.loc?.filter((p) => p !== "body").join(".");
          return field ? `${field}: ${d.msg}` : d.msg;
        })
        .join("; ");
    }
    if (!error.response) return "Không kết nối được máy chủ";
    return `Lỗi ${error.response.status}`;
  }
  return error instanceof Error ? error.message : "Đã có lỗi xảy ra";
}

/** Bỏ các trường rỗng ("" / undefined) trước khi gửi query/body. */
export function clean<T extends Record<string, unknown>>(obj: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(obj).filter(([, v]) => v !== "" && v !== undefined && !(Array.isArray(v) && v.length === 0)),
  ) as Partial<T>;
}
