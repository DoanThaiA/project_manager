"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { AlertTriangle, Ban, Copy, KeyRound, Pencil, Plus, Trash2, Zap } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button, IconButton } from "@/components/ui/button";
import { Checkbox, Field, Input, Select } from "@/components/ui/form";
import { Card, Empty, PageHeader, Pagination, ProgressBar, Spinner, Stat, Table } from "@/components/ui/misc";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useProjects } from "@/lib/hooks";
import type {
  LlmClientKey,
  LlmClientKeyCreated,
  LlmGatewayStatus,
  LlmModel,
  LlmProvider,
  LlmProviderKey,
  LlmUsageLog,
  LlmUsageSummary,
  Page,
} from "@/lib/types";
import { cn, fmtDate, fmtDateTime, fmtRelative } from "@/lib/utils";

type Tab = "usage" | "clients" | "providers" | "keys" | "models";
type ApiFormat = "openai" | "anthropic";

/** Mẫu điền nhanh khi thêm nhà cung cấp; base URL gồm phần phiên bản — kiểm tra lại theo tài liệu của hãng. */
const PRESETS: { code: string; name: string; api_format: ApiFormat; base_url: string }[] = [
  { code: "grok", name: "xAI Grok", api_format: "openai", base_url: "https://api.x.ai/v1" },
  { code: "deepseek", name: "DeepSeek", api_format: "openai", base_url: "https://api.deepseek.com/v1" },
  { code: "mistral", name: "Mistral", api_format: "openai", base_url: "https://api.mistral.ai/v1" },
  { code: "groq", name: "Groq", api_format: "openai", base_url: "https://api.groq.com/openai/v1" },
  { code: "openrouter", name: "OpenRouter", api_format: "openai", base_url: "https://openrouter.ai/api/v1" },
  {
    code: "gemini",
    name: "Google Gemini (tương thích OpenAI)",
    api_format: "openai",
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
  },
  { code: "ollama", name: "Ollama (nội bộ)", api_format: "openai", base_url: "http://localhost:11434/v1" },
];

/** base_url cho SDK của dự án: định dạng anthropic -> .../llm/{code}; openai -> .../llm/{code}/v1. */
function sdkBaseUrl(base: string, p: Pick<LlmProvider, "code" | "api_format">) {
  return p.api_format === "anthropic" ? `${base}/${p.code}` : `${base}/${p.code}/v1`;
}

function fmtUsd(v?: number | null) {
  const n = v ?? 0;
  return `$${n < 1 && n > 0 ? n.toFixed(4) : n.toFixed(2)}`;
}

function fmtTokens(n?: number | null) {
  return (n ?? 0).toLocaleString("vi-VN");
}

function useProviders() {
  const query = useQuery({
    queryKey: ["llm", "providers"],
    queryFn: async () => (await api.get<LlmProvider[]>("/llm/providers")).data,
  });
  const byCode = useMemo(() => new Map((query.data ?? []).map((p) => [p.code, p])), [query.data]);
  /** Tên hiển thị của mã nhà cung cấp. */
  const label = (code: string) => byCode.get(code)?.name ?? code;
  return { ...query, providers: query.data ?? [], label };
}

function useGatewayStatus() {
  return useQuery({
    queryKey: ["llm", "status"],
    queryFn: async () => (await api.get<LlmGatewayStatus>("/llm/status")).data,
  });
}

function useLlmModels() {
  return useQuery({
    queryKey: ["llm", "models"],
    queryFn: async () => (await api.get<LlmModel[]>("/llm/models")).data,
  });
}

export default function LlmGatewayPage() {
  const { can } = useAuth();
  const manage = can("llm.manage");
  const status = useGatewayStatus();
  const [tab, setTab] = useState<Tab>("usage");

  const tabs: [Tab, string][] = [
    ["usage", "Sử dụng & chi phí"],
    ["clients", "Key dự án"],
    ...(manage
      ? ([
          ["providers", "Nhà cung cấp"],
          ["keys", "Key nhà cung cấp"],
        ] as [Tab, string][])
      : []),
    ["models", "Model & giá"],
  ];

  return (
    <>
      <PageHeader
        title="AI Gateway"
        description="Dự án gọi Anthropic, OpenAI, Grok… qua gateway bằng key riêng, có hạn mức; key thật chỉ nằm ở đây"
      />
      {status.data && !status.data.enabled && (
        <Card className="mb-4 flex items-start gap-3 border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <p>
            <code className="font-mono">LLM_ENCRYPTION_KEY</code> trên server chưa đặt hoặc sai định dạng nên chưa lưu được key nhà cung cấp.
            Xem hướng dẫn trong <code className="font-mono">docs/LLM_GATEWAY.md</code>.
          </p>
        </Card>
      )}
      <Card>
        <div className="flex items-center gap-1 overflow-x-auto border-b border-line px-3 pt-2" role="tablist">
          {tabs.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-[13px] font-medium whitespace-nowrap transition-colors",
                tab === key ? "border-brand text-brand" : "border-transparent text-ink-3 hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {tab === "usage" && <UsageTab />}
        {tab === "clients" && <ClientKeysTab manage={manage} baseUrl={status.data?.public_base_url} />}
        {tab === "providers" && manage && <ProvidersTab />}
        {tab === "keys" && manage && <ProviderKeysTab />}
        {tab === "models" && <ModelsTab manage={manage} />}
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- Sử dụng & chi phí

function UsageTab() {
  const { label: providerLabel } = useProviders();
  const [month, setMonth] = useState(() => format(new Date(), "yyyy-MM"));
  const [page, setPage] = useState(1);
  const summary = useQuery({
    queryKey: ["llm", "usage", month],
    queryFn: async () => (await api.get<LlmUsageSummary>("/llm/usage/summary", { params: { month } })).data,
    placeholderData: keepPreviousData,
  });
  const errors = useQuery({
    queryKey: ["llm", "errors", page],
    queryFn: async () =>
      (await api.get<Page<LlmUsageLog>>("/llm/usage/logs", { params: { errors_only: true, page, size: 20 } })).data,
    placeholderData: keepPreviousData,
  });
  const s = summary.data;

  return (
    <>
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <Input
          type="month"
          aria-label="Tháng"
          className="w-40"
          value={month}
          max={format(new Date(), "yyyy-MM")}
          onChange={(e) => e.target.value && setMonth(e.target.value)}
        />
      </div>
      {summary.isPending ? (
        <Spinner />
      ) : (
        <div className="space-y-5 p-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Stat label="Chi phí" value={fmtUsd(s?.total.cost_usd)} />
            <Stat label="Request" value={fmtTokens(s?.total.requests)} />
            <Stat label="Token vào" value={fmtTokens((s?.total.input_tokens ?? 0) + (s?.total.cache_read_tokens ?? 0))} sub={`cache ${fmtTokens(s?.total.cache_read_tokens)}`} />
            <Stat label="Token ra" value={fmtTokens(s?.total.output_tokens)} />
            <Stat label="Lỗi" value={fmtTokens(s?.total.errors)} className={cn((s?.total.errors ?? 0) > 0 && "ring-1 ring-amber-200")} />
          </div>

          <Section title="Theo key dự án">
            {!s?.by_key.length ? (
              <Empty title="Chưa có request nào trong tháng" />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <th>Key</th>
                    <th>Dự án</th>
                    <th className="!text-right">Request</th>
                    <th className="!text-right">Token vào / ra</th>
                    <th className="!text-right">Chi phí</th>
                    <th className="w-48">Hạn mức tháng</th>
                  </tr>
                </thead>
                <tbody>
                  {s.by_key.map((r) => (
                    <tr key={r.client_key_id ?? "none"}>
                      <td className="font-medium">{r.name ?? "(key đã xoá)"}</td>
                      <td className="text-ink-2">{r.project ? `${r.project.key} · ${r.project.name}` : "—"}</td>
                      <td className="text-right tabular-nums">{fmtTokens(r.requests)}</td>
                      <td className="text-right tabular-nums">
                        {fmtTokens(r.input_tokens + r.cache_read_tokens)} / {fmtTokens(r.output_tokens)}
                      </td>
                      <td className="text-right font-semibold tabular-nums">{fmtUsd(r.cost_usd)}</td>
                      <td>
                        <BudgetBar spent={r.cost_usd} budget={r.monthly_budget_usd} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Section>

          <div className="grid gap-5 lg:grid-cols-2">
            <Section title="Theo model">
              <Table>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th className="!text-right">Request</th>
                    <th className="!text-right">Chi phí</th>
                  </tr>
                </thead>
                <tbody>
                  {(s?.by_model ?? []).map((r) => (
                    <tr key={`${r.provider}/${r.model}`}>
                      <td>
                        <span className="font-mono text-[13px]">{r.model ?? "—"}</span>
                        <span className="ml-2 text-xs text-ink-3">{providerLabel(r.provider)}</span>
                      </td>
                      <td className="text-right tabular-nums">{fmtTokens(r.requests)}</td>
                      <td className="text-right tabular-nums">{fmtUsd(r.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Section>
            <Section title="Theo ngày">
              <Table>
                <thead>
                  <tr>
                    <th>Ngày</th>
                    <th className="!text-right">Request</th>
                    <th className="!text-right">Chi phí</th>
                  </tr>
                </thead>
                <tbody>
                  {(s?.by_day ?? []).map((r) => (
                    <tr key={r.date}>
                      <td className="tabular-nums">{format(parseISO(r.date), "dd/MM")}</td>
                      <td className="text-right tabular-nums">{fmtTokens(r.requests)}</td>
                      <td className="text-right tabular-nums">{fmtUsd(r.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Section>
          </div>

          <Section title="Lỗi gần đây">
            {!errors.data?.items.length ? (
              <Empty title="Không có lỗi" />
            ) : (
              <>
                <Table>
                  <thead>
                    <tr>
                      <th>Thời điểm</th>
                      <th>Key</th>
                      <th>Model</th>
                      <th className="!text-right">Mã</th>
                      <th>Lỗi</th>
                    </tr>
                  </thead>
                  <tbody>
                    {errors.data.items.map((e) => (
                      <tr key={e.id}>
                        <td className="whitespace-nowrap tabular-nums">{fmtDateTime(e.created_at)}</td>
                        <td>{e.client_key_name ?? "—"}</td>
                        <td className="font-mono text-[13px]">{e.model ?? "—"}</td>
                        <td className="text-right tabular-nums">{e.status_code}</td>
                        <td className="max-w-96 truncate text-xs text-ink-3" title={e.error ?? undefined}>
                          {e.error ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
                <Pagination page={page} size={20} total={errors.data.total} onChange={setPage} />
              </>
            )}
          </Section>
        </div>
      )}
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <div className="border-b border-line bg-subtle/60 px-4 py-2 text-[13px] font-semibold">{title}</div>
      {children}
    </div>
  );
}

function BudgetBar({ spent, budget }: { spent: number; budget?: number | null }) {
  if (budget === null || budget === undefined) return <span className="text-xs text-ink-3">Không giới hạn</span>;
  const pct = budget > 0 ? (spent / budget) * 100 : 100;
  return (
    <div className="space-y-1">
      <ProgressBar value={pct} className={cn(pct >= 100 && "[&>div]:bg-red-500", pct >= 80 && pct < 100 && "[&>div]:bg-amber-500")} />
      <p className="text-xs text-ink-3 tabular-nums">
        {fmtUsd(spent)} / {fmtUsd(budget)}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------- Key dự án

function ClientKeysTab({ manage, baseUrl }: { manage: boolean; baseUrl?: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState<LlmClientKey | "new" | null>(null);
  const [created, setCreated] = useState<LlmClientKeyCreated | null>(null);
  const keys = useQuery({
    queryKey: ["llm", "client-keys"],
    queryFn: async () => (await api.get<LlmClientKey[]>("/llm/client-keys")).data,
  });
  const revoke = useMutation({
    mutationFn: (id: number) => api.post(`/llm/client-keys/${id}/revoke`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm"] });
      toast.success("Đã thu hồi key");
    },
    onError: toast.error,
  });

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3 text-sm text-ink-3">
        <span>
          SDK trỏ <code className="font-mono text-ink-2">base_url</code> vào{" "}
          <code className="font-mono text-ink-2">{baseUrl ?? "…/llm"}/&lt;mã nhà cung cấp&gt;</code> (Anthropic) hoặc{" "}
          <code className="font-mono text-ink-2">…/&lt;mã&gt;/v1</code> (định dạng OpenAI)
        </span>
        {manage && (
          <Button size="sm" variant="primary" className="ml-auto" icon={<Plus className="size-4" />} onClick={() => setEditing("new")}>
            Cấp key
          </Button>
        )}
      </div>
      {keys.isPending ? (
        <Spinner />
      ) : !keys.data?.length ? (
        <Empty title="Chưa cấp key nào" description="Mỗi dự án nên có key riêng để theo dõi chi phí và thu hồi độc lập." />
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Tên</th>
              <th>Dự án</th>
              <th>Key</th>
              <th>Model</th>
              <th className="w-48">Hạn mức tháng</th>
              <th>Giới hạn</th>
              <th>Dùng lần cuối</th>
              {manage && <th className="w-20" />}
            </tr>
          </thead>
          <tbody>
            {keys.data.map((k) => (
              <tr key={k.id} className={cn(k.revoked_at && "opacity-60")}>
                <td className="font-medium">
                  {k.name}
                  {k.revoked_at && (
                    <Badge tone="red" className="ml-2">
                      Đã thu hồi
                    </Badge>
                  )}
                  {!k.revoked_at && k.expires_at && new Date(k.expires_at) < new Date() && (
                    <Badge tone="amber" className="ml-2">
                      Hết hạn
                    </Badge>
                  )}
                </td>
                <td className="text-ink-2">{k.project ? `${k.project.key} · ${k.project.name}` : "—"}</td>
                <td className="font-mono text-[13px]">{k.key_prefix}</td>
                <td className="max-w-56 text-xs text-ink-2">{k.allowed_models.length ? k.allowed_models.join(", ") : "Tất cả model đang bật"}</td>
                <td>
                  <BudgetBar spent={k.spent_this_month ?? 0} budget={k.monthly_budget_usd} />
                </td>
                <td className="text-xs whitespace-nowrap text-ink-2">
                  {k.rpm_limit ? `${k.rpm_limit} req/phút` : "—"}
                  {k.expires_at && <span className="block">Hết hạn {fmtDate(k.expires_at)}</span>}
                </td>
                <td className="text-xs whitespace-nowrap text-ink-3">{k.last_used_at ? fmtRelative(k.last_used_at) : "Chưa dùng"}</td>
                {manage && (
                  <td>
                    {!k.revoked_at && (
                      <div className="flex justify-end gap-0.5">
                        <IconButton label="Sửa" onClick={() => setEditing(k)}>
                          <Pencil className="size-4" />
                        </IconButton>
                        <IconButton
                          label="Thu hồi"
                          onClick={() => confirm(`Thu hồi key "${k.name}"? Dự án dùng key này sẽ bị chặn ngay.`) && revoke.mutate(k.id)}
                        >
                          <Ban className="size-4" />
                        </IconButton>
                      </div>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {editing && (
        <ClientKeyModal
          clientKey={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onCreated={setCreated}
        />
      )}
      {created && <CreatedKeyModal created={created} baseUrl={baseUrl} onClose={() => setCreated(null)} />}
    </>
  );
}

function ClientKeyModal({
  clientKey,
  onClose,
  onCreated,
}: {
  clientKey?: LlmClientKey;
  onClose: () => void;
  onCreated: (k: LlmClientKeyCreated) => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const projects = useProjects();
  const models = useLlmModels();
  const { label: providerLabel } = useProviders();
  const editing = !!clientKey;
  const [form, setForm] = useState({
    name: clientKey?.name ?? "",
    project_id: clientKey?.project_id ? String(clientKey.project_id) : "",
    allowed_models: clientKey?.allowed_models ?? [],
    monthly_budget_usd: clientKey?.monthly_budget_usd != null ? String(clientKey.monthly_budget_usd) : "",
    rpm_limit: clientKey?.rpm_limit != null ? String(clientKey.rpm_limit) : "",
    expires_at: clientKey?.expires_at ? format(parseISO(clientKey.expires_at), "yyyy-MM-dd") : "",
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: form.name.trim(),
        project_id: form.project_id ? Number(form.project_id) : null,
        allowed_models: form.allowed_models,
        monthly_budget_usd: form.monthly_budget_usd ? Number(form.monthly_budget_usd) : null,
        rpm_limit: form.rpm_limit ? Number(form.rpm_limit) : null,
        expires_at: form.expires_at ? `${form.expires_at}T23:59:59+07:00` : null,
      };
      if (editing) {
        await api.patch(`/llm/client-keys/${clientKey.id}`, body);
        return null;
      }
      return (await api.post<LlmClientKeyCreated>("/llm/client-keys", body)).data;
    },
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ["llm"] });
      if (created) onCreated(created);
      else toast.success("Đã lưu key");
      onClose();
    },
    onError: toast.error,
  });
  const valid = form.name.trim() && (!form.monthly_budget_usd || Number(form.monthly_budget_usd) >= 0);
  const activeModels = (models.data ?? []).filter((m) => m.is_active);

  return (
    <Modal
      open
      onClose={onClose}
      title={editing ? `Sửa key ${clientKey.name}` : "Cấp key cho dự án"}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button variant="primary" loading={save.isPending} disabled={!valid} onClick={() => save.mutate()}>
            {editing ? "Lưu" : "Cấp key"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Tên key" required>
          {(id) => <Input id={id} value={form.name} placeholder="VD: ERP backend" onChange={(e) => set("name", e.target.value)} />}
        </Field>
        <Field label="Dự án">
          {(id) => (
            <Select id={id} value={form.project_id} onChange={(e) => set("project_id", e.target.value)}>
              <option value="">Không gắn dự án</option>
              {(projects.data?.items ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.key} · {p.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Hạn mức tháng (USD)" hint="Bỏ trống = không giới hạn">
          {(id) => (
            <Input id={id} type="number" min={0} step="0.01" value={form.monthly_budget_usd} onChange={(e) => set("monthly_budget_usd", e.target.value)} />
          )}
        </Field>
        <Field label="Giới hạn request / phút" hint="Bỏ trống = không giới hạn">
          {(id) => <Input id={id} type="number" min={1} value={form.rpm_limit} onChange={(e) => set("rpm_limit", e.target.value)} />}
        </Field>
        <Field label="Hết hạn" hint="Bỏ trống = không hết hạn">
          {(id) => <Input id={id} type="date" value={form.expires_at} onChange={(e) => set("expires_at", e.target.value)} />}
        </Field>
        <fieldset className="sm:col-span-2">
          <legend className="mb-1.5 text-[13px] font-medium text-ink-2">Model được dùng (không chọn = tất cả model đang bật)</legend>
          {!activeModels.length ? (
            <p className="text-sm text-ink-3">Chưa bật model nào — thêm ở tab Model & giá.</p>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {activeModels.map((m) => (
                <Checkbox
                  key={m.id}
                  label={
                    <span>
                      <span className="font-mono text-[13px]">{m.model}</span>
                      <span className="ml-1.5 text-xs text-ink-3">{providerLabel(m.provider)}</span>
                    </span>
                  }
                  checked={form.allowed_models.includes(m.model)}
                  onChange={(e) =>
                    set(
                      "allowed_models",
                      e.target.checked ? [...form.allowed_models, m.model] : form.allowed_models.filter((x) => x !== m.model),
                    )
                  }
                />
              ))}
            </div>
          )}
        </fieldset>
      </div>
    </Modal>
  );
}

function CreatedKeyModal({ created, baseUrl, onClose }: { created: LlmClientKeyCreated; baseUrl?: string; onClose: () => void }) {
  const toast = useToast();
  const { providers } = useProviders();
  const base = baseUrl ?? "https://<domain>/llm";
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Đã copy");
    } catch {
      toast.error("Không copy được, hãy chọn và copy tay");
    }
  };
  // Một đoạn code mẫu cho mỗi nhà cung cấp đang bật: định dạng anthropic dùng Anthropic SDK, còn lại OpenAI SDK
  const snippets = providers
    .filter((p) => p.is_active)
    .map((p) =>
      p.api_format === "anthropic"
        ? [`${p.name} · Anthropic SDK (Python)`, `from anthropic import Anthropic\n\nclient = Anthropic(base_url="${sdkBaseUrl(base, p)}", api_key="${created.key}")`]
        : [`${p.name} · OpenAI SDK (Python)`, `from openai import OpenAI\n\nclient = OpenAI(base_url="${sdkBaseUrl(base, p)}", api_key="${created.key}")`],
    );
  return (
    <Modal
      open
      onClose={onClose}
      title={`Key cho ${created.name}`}
      description="Key chỉ hiện MỘT LẦN — copy và gửi cho dự án ngay. Mất key thì thu hồi và cấp key mới."
      footer={
        <Button variant="primary" onClick={onClose}>
          Đã lưu key
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="flex items-center gap-2 rounded-lg border border-line bg-subtle/60 p-2">
          <KeyRound className="size-4 shrink-0 text-ink-3" />
          <code className="min-w-0 flex-1 truncate font-mono text-[13px]">{created.key}</code>
          <IconButton label="Copy key" onClick={() => copy(created.key)}>
            <Copy className="size-4" />
          </IconButton>
        </div>
        {snippets.map(([title, code]) => (
          <div key={title}>
            <div className="mb-1 flex items-center justify-between">
              <p className="text-[13px] font-medium text-ink-2">{title}</p>
              <Button size="sm" variant="ghost" icon={<Copy className="size-3.5" />} onClick={() => copy(code)}>
                Copy
              </Button>
            </div>
            <pre className="overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">{code}</pre>
          </div>
        ))}
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- Nhà cung cấp

function ProvidersTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const status = useGatewayStatus();
  const { providers, isPending } = useProviders();
  const [editing, setEditing] = useState<LlmProvider | "new" | null>(null);
  const remove = useMutation({
    mutationFn: (code: string) => api.delete(`/llm/providers/${code}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm", "providers"] });
      toast.success("Đã xoá nhà cung cấp");
    },
    onError: toast.error,
  });
  const base = status.data?.public_base_url ?? "…/llm";

  return (
    <>
      <div className="flex items-center gap-2 border-b border-line px-4 py-3 text-sm text-ink-3">
        <span>
          Nhà cung cấp dùng định dạng OpenAI (Grok, DeepSeek, OpenRouter, Ollama…) hoặc Anthropic. Mỗi nhà cung cấp có
          đường dẫn riêng trên gateway.
        </span>
        <Button size="sm" variant="primary" className="ml-auto shrink-0" icon={<Plus className="size-4" />} onClick={() => setEditing("new")}>
          Thêm nhà cung cấp
        </Button>
      </div>
      {isPending ? (
        <Spinner />
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Nhà cung cấp</th>
              <th>Định dạng</th>
              <th>Base URL</th>
              <th>base_url cho SDK của dự án</th>
              <th className="!text-right">Key / Model</th>
              <th>Trạng thái</th>
              <th className="w-20" />
            </tr>
          </thead>
          <tbody>
            {providers.map((p) => (
              <tr key={p.code}>
                <td>
                  <span className="font-medium">{p.name}</span>
                  <span className="ml-2 font-mono text-xs text-ink-3">{p.code}</span>
                  {p.is_builtin && (
                    <Badge tone="indigo" className="ml-2">
                      Có sẵn
                    </Badge>
                  )}
                </td>
                <td>{p.api_format === "anthropic" ? "Anthropic" : "OpenAI"}</td>
                <td className="max-w-64 truncate font-mono text-xs" title={p.base_url}>
                  {p.base_url}
                </td>
                <td className="max-w-64 truncate font-mono text-xs text-ink-2" title={sdkBaseUrl(base, p)}>
                  {sdkBaseUrl(base, p)}
                </td>
                <td className="text-right tabular-nums">
                  {p.key_count} / {p.model_count}
                </td>
                <td>{p.is_active ? <Badge tone="green">Bật</Badge> : <Badge tone="gray">Tắt</Badge>}</td>
                <td>
                  <div className="flex justify-end gap-0.5">
                    <IconButton label="Sửa" onClick={() => setEditing(p)}>
                      <Pencil className="size-4" />
                    </IconButton>
                    {!p.is_builtin && (
                      <IconButton label="Xoá" onClick={() => confirm(`Xoá nhà cung cấp ${p.name}?`) && remove.mutate(p.code)}>
                        <Trash2 className="size-4" />
                      </IconButton>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {editing && <ProviderModal provider={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function ProviderModal({ provider, onClose }: { provider?: LlmProvider; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const editing = !!provider;
  const [form, setForm] = useState({
    code: provider?.code ?? "",
    name: provider?.name ?? "",
    api_format: (provider?.api_format ?? "openai") as ApiFormat,
    base_url: provider?.base_url ?? "",
    extra_headers: Object.entries(provider?.extra_headers ?? {})
      .map(([k, v]) => `${k}: ${v}`)
      .join("\n"),
    stream_usage: provider?.stream_usage ?? true,
    is_active: provider?.is_active ?? true,
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));
  const applyPreset = (code: string) => {
    const preset = PRESETS.find((x) => x.code === code);
    if (preset) setForm((f) => ({ ...f, ...preset }));
  };

  // "Tên: giá trị" mỗi dòng -> object; dòng sai định dạng thì báo lỗi
  const headerLines = form.extra_headers.split("\n").map((l) => l.trim()).filter(Boolean);
  const headersValid = headerLines.every((l) => /^[A-Za-z0-9-]+\s*:\s*\S/.test(l));
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: form.name.trim(),
        api_format: form.api_format,
        base_url: form.base_url.trim(),
        extra_headers: Object.fromEntries(
          headerLines.map((l) => {
            const i = l.indexOf(":");
            return [l.slice(0, i).trim(), l.slice(i + 1).trim()];
          }),
        ),
        stream_usage: form.stream_usage,
        is_active: form.is_active,
      };
      if (editing) await api.put(`/llm/providers/${provider.code}`, body);
      else await api.post("/llm/providers", { ...body, code: form.code.trim() });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm"] });
      toast.success(editing ? "Đã lưu nhà cung cấp" : "Đã thêm nhà cung cấp");
      onClose();
    },
    onError: toast.error,
  });
  const valid =
    form.name.trim() &&
    /^https?:\/\//.test(form.base_url.trim()) &&
    headersValid &&
    (editing || /^[a-z0-9][a-z0-9-]{1,29}$/.test(form.code.trim()));

  return (
    <Modal
      open
      onClose={onClose}
      title={editing ? `Sửa ${provider.name}` : "Thêm nhà cung cấp"}
      description="Sau khi lưu: thêm key ở tab Key nhà cung cấp, thêm model + giá ở tab Model & giá."
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button variant="primary" loading={save.isPending} disabled={!valid} onClick={() => save.mutate()}>
            Lưu
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {!editing && (
          <Field label="Điền nhanh từ mẫu" className="sm:col-span-2" hint="Base URL theo tài liệu của hãng; bấm ⚡ ở key để kiểm tra">
            {(id) => (
              <Select id={id} value="" onChange={(e) => applyPreset(e.target.value)}>
                <option value="">Chọn mẫu…</option>
                {PRESETS.map((x) => (
                  <option key={x.code} value={x.code}>
                    {x.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
        <Field label="Mã" required hint="Chữ thường, số, gạch ngang; dùng trong đường dẫn /llm/<mã>/v1">
          {(id) => (
            <Input id={id} className="font-mono" value={form.code} disabled={editing} placeholder="grok" onChange={(e) => set("code", e.target.value.toLowerCase())} />
          )}
        </Field>
        <Field label="Tên" required>
          {(id) => <Input id={id} value={form.name} placeholder="xAI Grok" onChange={(e) => set("name", e.target.value)} />}
        </Field>
        <Field label="Định dạng API" required hint="Hầu hết nhà cung cấp tương thích OpenAI">
          {(id) => (
            <Select id={id} value={form.api_format} disabled={provider?.is_builtin} onChange={(e) => set("api_format", e.target.value as ApiFormat)}>
              <option value="openai">OpenAI (Bearer, /chat/completions)</option>
              <option value="anthropic">Anthropic (x-api-key, /messages)</option>
            </Select>
          )}
        </Field>
        <Field label="Base URL" required hint="Gồm phần phiên bản, vd https://api.x.ai/v1">
          {(id) => <Input id={id} className="font-mono" value={form.base_url} placeholder="https://…/v1" onChange={(e) => set("base_url", e.target.value)} />}
        </Field>
        <Field label="Header bổ sung" className="sm:col-span-2" hint="Mỗi dòng một header dạng Tên: giá trị. Không đặt key bí mật ở đây.">
          {(id) => (
            <textarea
              id={id}
              rows={2}
              value={form.extra_headers}
              placeholder="HTTP-Referer: https://dev.mcv.network"
              onChange={(e) => set("extra_headers", e.target.value)}
              className={cn(
                "w-full rounded-lg border bg-surface px-3 py-2 font-mono text-sm focus:ring-2 focus:ring-brand/20 focus:outline-none",
                headersValid ? "border-line-strong focus:border-brand" : "border-red-400",
              )}
            />
          )}
        </Field>
        {form.api_format === "openai" && (
          <Checkbox
            className="sm:col-span-2"
            label="Tự bật stream_options.include_usage khi stream (để tính chi phí) — tắt nếu nhà cung cấp báo lỗi tham số này"
            checked={form.stream_usage}
            onChange={(e) => set("stream_usage", e.target.checked)}
          />
        )}
        <Checkbox className="sm:col-span-2" label="Bật" checked={form.is_active} onChange={(e) => set("is_active", e.target.checked)} />
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- Key nhà cung cấp

function ProviderKeysTab() {
  const { label: providerLabel } = useProviders();
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState<LlmProviderKey | "new" | null>(null);
  const keys = useQuery({
    queryKey: ["llm", "provider-keys"],
    queryFn: async () => (await api.get<LlmProviderKey[]>("/llm/provider-keys")).data,
  });
  const test = useMutation({
    mutationFn: async (id: number) => (await api.post<{ ok: boolean; message: string }>(`/llm/provider-keys/${id}/test`)).data,
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["llm", "provider-keys"] });
      if (r.ok) toast.success(r.message);
      else toast.error(r.message);
    },
    onError: toast.error,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/llm/provider-keys/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm", "provider-keys"] });
      toast.success("Đã xoá key");
    },
    onError: toast.error,
  });

  return (
    <>
      <div className="flex items-center gap-2 border-b border-line px-4 py-3 text-sm text-ink-3">
        <span>Key được mã hoá trong database, không hiển thị lại. Nhiều key cùng nhà cung cấp: ưu tiên cao dùng trước, key lỗi tự tạm nghỉ.</span>
        <Button size="sm" variant="primary" className="ml-auto shrink-0" icon={<Plus className="size-4" />} onClick={() => setEditing("new")}>
          Thêm key
        </Button>
      </div>
      {keys.isPending ? (
        <Spinner />
      ) : !keys.data?.length ? (
        <Empty title="Chưa có key nhà cung cấp" description="Thêm key của Anthropic, OpenAI hoặc nhà cung cấp khác để gateway gọi được." />
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Nhà cung cấp</th>
              <th>Tên</th>
              <th>Key</th>
              <th className="!text-right">Ưu tiên</th>
              <th>Trạng thái</th>
              <th>Lỗi gần nhất</th>
              <th>Dùng lần cuối</th>
              <th className="w-28" />
            </tr>
          </thead>
          <tbody>
            {keys.data.map((k) => {
              const cooling = k.cooldown_until && new Date(k.cooldown_until) > new Date();
              return (
                <tr key={k.id}>
                  <td>{providerLabel(k.provider)}</td>
                  <td className="font-medium">{k.name}</td>
                  <td className="font-mono text-[13px]">{k.key_hint}</td>
                  <td className="text-right tabular-nums">{k.priority}</td>
                  <td>
                    {!k.is_active ? (
                      <Badge tone="gray">Tắt</Badge>
                    ) : cooling ? (
                      <Badge tone="amber">Tạm nghỉ đến {format(parseISO(k.cooldown_until!), "HH:mm")}</Badge>
                    ) : (
                      <Badge tone="green">Đang dùng</Badge>
                    )}
                  </td>
                  <td className="max-w-64 truncate text-xs text-ink-3" title={k.last_error ?? undefined}>
                    {k.last_error ? `${fmtRelative(k.last_error_at)} · ${k.last_error}` : "—"}
                  </td>
                  <td className="text-xs whitespace-nowrap text-ink-3">{k.last_used_at ? fmtRelative(k.last_used_at) : "Chưa dùng"}</td>
                  <td>
                    <div className="flex justify-end gap-0.5">
                      <IconButton label="Kiểm tra key" disabled={test.isPending} onClick={() => test.mutate(k.id)}>
                        <Zap className="size-4" />
                      </IconButton>
                      <IconButton label="Sửa" onClick={() => setEditing(k)}>
                        <Pencil className="size-4" />
                      </IconButton>
                      <IconButton label="Xoá" onClick={() => confirm(`Xoá key ${k.name} (${k.key_hint})?`) && remove.mutate(k.id)}>
                        <Trash2 className="size-4" />
                      </IconButton>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
      {editing && <ProviderKeyModal providerKey={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function ProviderKeyModal({ providerKey, onClose }: { providerKey?: LlmProviderKey; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const editing = !!providerKey;
  const { providers } = useProviders();
  const [form, setForm] = useState({
    provider: providerKey?.provider ?? "anthropic",
    name: providerKey?.name ?? "",
    api_key: "",
    base_url: providerKey?.base_url ?? "",
    priority: providerKey?.priority ?? 0,
    is_active: providerKey?.is_active ?? true,
    reset_cooldown: false,
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));

  const save = useMutation({
    mutationFn: async () => {
      const common = { name: form.name.trim(), base_url: form.base_url.trim() || null, priority: form.priority, is_active: form.is_active };
      if (editing) {
        await api.patch(`/llm/provider-keys/${providerKey.id}`, {
          ...common,
          ...(form.api_key.trim() ? { api_key: form.api_key.trim() } : {}),
          reset_cooldown: form.reset_cooldown,
        });
      } else {
        await api.post("/llm/provider-keys", { ...common, provider: form.provider, api_key: form.api_key.trim() });
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm", "provider-keys"] });
      toast.success(editing ? "Đã lưu key" : "Đã thêm key");
      onClose();
    },
    onError: toast.error,
  });
  const valid = form.name.trim() && (editing || form.api_key.trim().length >= 10);

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={editing ? `Sửa key ${providerKey.name}` : "Thêm key nhà cung cấp"}
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button variant="primary" loading={save.isPending} disabled={!valid} onClick={() => save.mutate()}>
            Lưu
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <Field label="Nhà cung cấp" required>
          {(id) => (
            <Select id={id} value={form.provider} disabled={editing} onChange={(e) => set("provider", e.target.value)}>
              {providers.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Tên" required>
          {(id) => <Input id={id} value={form.name} placeholder="VD: Anthropic công ty" onChange={(e) => set("name", e.target.value)} />}
        </Field>
        <Field
          label="API key"
          required={!editing}
          hint={editing ? `Đang dùng ${providerKey.key_hint}. Bỏ trống = giữ key cũ` : "Chỉ lưu dạng mã hoá, không hiển thị lại"}
        >
          {(id) => (
            <Input id={id} type="password" autoComplete="off" className="font-mono" value={form.api_key} onChange={(e) => set("api_key", e.target.value)} />
          )}
        </Field>
        <Field label="Base URL riêng cho key này" hint="Bỏ trống = base URL của nhà cung cấp (gồm /v1)">
          {(id) => <Input id={id} value={form.base_url} placeholder="https://…" onChange={(e) => set("base_url", e.target.value)} />}
        </Field>
        <Field label="Độ ưu tiên (0–100)" hint="Cao hơn được dùng trước">
          {(id) => (
            <Input id={id} type="number" min={0} max={100} value={form.priority} onChange={(e) => set("priority", Number(e.target.value))} />
          )}
        </Field>
        <Checkbox label="Đang dùng" checked={form.is_active} onChange={(e) => set("is_active", e.target.checked)} />
        {editing && (
          <Checkbox
            label="Cho dùng lại ngay (bỏ tạm nghỉ, xoá lỗi gần nhất)"
            checked={form.reset_cooldown}
            onChange={(e) => set("reset_cooldown", e.target.checked)}
          />
        )}
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- Model & giá

function ModelsTab({ manage }: { manage: boolean }) {
  const { label: providerLabel } = useProviders();
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState<LlmModel | "new" | null>(null);
  const models = useLlmModels();
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/llm/models/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm", "models"] });
      toast.success("Đã xoá model");
    },
    onError: toast.error,
  });

  return (
    <>
      <div className="flex items-center gap-2 border-b border-line px-4 py-3 text-sm text-ink-3">
        <span>Chỉ model có trong danh sách và đang bật mới gọi được. Giá USD / 1 triệu token, dùng để tính chi phí và hạn mức.</span>
        {manage && (
          <Button size="sm" variant="primary" className="ml-auto shrink-0" icon={<Plus className="size-4" />} onClick={() => setEditing("new")}>
            Thêm model
          </Button>
        )}
      </div>
      {models.isPending ? (
        <Spinner />
      ) : !models.data?.length ? (
        <Empty title="Chưa có model nào" description="Thêm model, ví dụ claude-sonnet-5-5, kèm giá theo bảng giá của nhà cung cấp." />
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Model</th>
              <th>Nhà cung cấp</th>
              <th className="!text-right">Vào</th>
              <th className="!text-right">Ra</th>
              <th className="!text-right">Đọc cache</th>
              <th className="!text-right">Ghi cache</th>
              <th>Trạng thái</th>
              {manage && <th className="w-20" />}
            </tr>
          </thead>
          <tbody>
            {models.data.map((m) => (
              <tr key={m.id}>
                <td className="font-mono text-[13px]">{m.model}</td>
                <td>{providerLabel(m.provider)}</td>
                <td className="text-right tabular-nums">${m.input_price}</td>
                <td className="text-right tabular-nums">${m.output_price}</td>
                <td className="text-right tabular-nums text-ink-2">{m.cache_read_price != null ? `$${m.cache_read_price}` : "= vào"}</td>
                <td className="text-right tabular-nums text-ink-2">{m.cache_write_price != null ? `$${m.cache_write_price}` : "= vào"}</td>
                <td>{m.is_active ? <Badge tone="green">Bật</Badge> : <Badge tone="gray">Tắt</Badge>}</td>
                {manage && (
                  <td>
                    <div className="flex justify-end gap-0.5">
                      <IconButton label="Sửa" onClick={() => setEditing(m)}>
                        <Pencil className="size-4" />
                      </IconButton>
                      <IconButton label="Xoá" onClick={() => confirm(`Xoá model ${m.model}?`) && remove.mutate(m.id)}>
                        <Trash2 className="size-4" />
                      </IconButton>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {editing && <ModelModal model={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function ModelModal({ model, onClose }: { model?: LlmModel; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const editing = !!model;
  const { providers } = useProviders();
  const [form, setForm] = useState({
    provider: model?.provider ?? "anthropic",
    model: model?.model ?? "",
    input_price: String(model?.input_price ?? ""),
    output_price: String(model?.output_price ?? ""),
    cache_read_price: model?.cache_read_price != null ? String(model.cache_read_price) : "",
    cache_write_price: model?.cache_write_price != null ? String(model.cache_write_price) : "",
    is_active: model?.is_active ?? true,
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));
  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        provider: form.provider,
        model: form.model.trim(),
        input_price: num(form.input_price) ?? 0,
        output_price: num(form.output_price) ?? 0,
        cache_read_price: num(form.cache_read_price),
        cache_write_price: num(form.cache_write_price),
        is_active: form.is_active,
      };
      if (editing) await api.put(`/llm/models/${model.id}`, body);
      else await api.post("/llm/models", body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["llm", "models"] });
      toast.success(editing ? "Đã lưu model" : "Đã thêm model");
      onClose();
    },
    onError: toast.error,
  });

  const priceField = (label: string, key: "input_price" | "output_price" | "cache_read_price" | "cache_write_price", hint?: string) => (
    <Field label={label} hint={hint}>
      {(id) => <Input id={id} type="number" min={0} step="0.0001" value={form[key]} onChange={(e) => set(key, e.target.value)} />}
    </Field>
  );

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={editing ? `Sửa model ${model.model}` : "Thêm model"}
      description="Giá USD / 1 triệu token, lấy từ bảng giá của nhà cung cấp"
      footer={
        <>
          <Button onClick={onClose}>Huỷ</Button>
          <Button variant="primary" loading={save.isPending} disabled={!form.model.trim()} onClick={() => save.mutate()}>
            Lưu
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nhà cung cấp" required>
          {(id) => (
            <Select id={id} value={form.provider} onChange={(e) => set("provider", e.target.value)}>
              {providers.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Tên model" required hint="Đúng tên model gửi lên nhà cung cấp">
          {(id) => (
            <Input id={id} className="font-mono" value={form.model} placeholder="claude-sonnet-5-5" onChange={(e) => set("model", e.target.value)} />
          )}
        </Field>
        {priceField("Giá vào", "input_price")}
        {priceField("Giá ra", "output_price")}
        {priceField("Giá đọc cache", "cache_read_price", "Bỏ trống = giá vào")}
        {priceField("Giá ghi cache", "cache_write_price", "Bỏ trống = giá vào")}
        <Checkbox className="sm:col-span-2" label="Bật (cho phép gọi)" checked={form.is_active} onChange={(e) => set("is_active", e.target.checked)} />
      </div>
    </Modal>
  );
}
