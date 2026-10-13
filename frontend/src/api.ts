import type { Session } from "./types";

export class ApiError extends Error {
  constructor(
    public code: string,
    public status: number,
  ) {
    super(code);
  }
}
const messages: Record<string, string> = {
  UNAUTHORIZED: "登录已失效，请重新选择身份登录。",
  FORBIDDEN: "当前身份无权进行这项操作。",
  RESOURCE_NOT_FOUND: "无法访问该资源，请检查订单或当前身份。",
  RUN_ACTIVE: "本会话仍有任务运行，请等待或停止后再发送。",
  CONFIRMATION_EXPIRED: "确认摘要已过期，请重新生成并核对。",
  VERSION_CONFLICT: "申请已更新，请刷新并重新核对当前状态。",
  IDEMPOTENCY_CONFLICT: "该操作内容已变化，请刷新后重新操作。",
  CONFIRMATION_REQUIRED: "请先由订单客户确认申请摘要。",
  MANUAL_REVIEW_REQUIRED: "当前规则要求人工核查，不能自动创建申请。",
  POLICY_UNAVAILABLE: "当前政策不可用，请转人工核查。",
  DATABASE_UNAVAILABLE: "暂时无法连接业务数据库，请稍后刷新。",
  NETWORK_UNKNOWN:
    "连接中断，操作结果暂时未知。请刷新状态，重试会复用同一请求。",
  INVALID_STATE: "当前状态不允许这项操作，请刷新状态。",
  INVALID_ARGUMENT: "请检查填写内容和所选订单。",
  INVALID_STATE_TRANSITION: "当前状态不允许这项操作，请重新读取申请。",
  ACTIVE_CASE_EXISTS: "这笔订单已有正在处理的申请，请在申请列表查看。",
};
export function errorText(error: unknown): string {
  return error instanceof ApiError
    ? (messages[error.code] ??
        `操作未完成（${error.code}）。请刷新状态后重试。`)
    : "操作未完成，请刷新状态后重试。";
}

export class Api {
  constructor(public session: Session) {}
  async key(path: string, body: unknown) {
    const bytes = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(JSON.stringify([path, body])),
    );
    const digest = [...new Uint8Array(bytes)]
      .map((v) => v.toString(16).padStart(2, "0"))
      .join("");
    const name = `m5:write:${this.session.user_id}:${digest}`;
    let key = sessionStorage.getItem(name);
    if (!key) {
      key = `ui-${crypto.randomUUID()}`;
      sessionStorage.setItem(name, key);
    }
    return key;
  }
  async request<T>(
    path: string,
    body?: unknown,
    signal?: AbortSignal,
    intent?: string,
  ): Promise<T> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.session.access_token}`,
    };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      headers["Idempotency-Key"] = await this.key(
        path,
        intent ? { body, intent } : body,
      );
    }
    let response: Response;
    try {
      response = await fetch(`/api/v1${path}`, {
        method: body === undefined ? "GET" : "POST",
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      throw new ApiError("NETWORK_UNKNOWN", 0);
    }
    const payload = await response.json();
    if (!response.ok || !payload.ok)
      throw new ApiError(payload.code ?? "NETWORK_UNKNOWN", response.status);
    return payload.data as T;
  }
}
export async function login(user_id: string): Promise<Session> {
  let response: Response;
  try {
    response = await fetch("/api/v1/dev/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id }),
    });
  } catch {
    throw new ApiError("NETWORK_UNKNOWN", 0);
  }
  const result = await response.json();
  if (!response.ok) throw new ApiError(result.code, response.status);
  const session = result.data as Session;
  sessionStorage.setItem("m5:session", JSON.stringify(session));
  return session;
}
export function storedSession(): Session | null {
  try {
    const value = JSON.parse(sessionStorage.getItem("m5:session") ?? "null");
    return value &&
      typeof value.access_token === "string" &&
      typeof value.user_id === "string"
      ? value
      : null;
  } catch {
    return null;
  }
}
