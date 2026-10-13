import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Api, ApiError, errorText, login, storedSession } from "./api";
import { date, eventLabels, label, money, toolLabels } from "./labels";
import type {
  Case,
  Confirmation,
  Conversation,
  Event,
  Evidence,
  Identity,
  Message,
  Order,
  Page,
  Policy,
  Refund,
  Run,
  Session,
  Ticket,
  Timeline,
} from "./types";

const identities = [
  ["C-A1", "客户 · A店"],
  ["C-A2", "客户二 · A店"],
  ["C-B1", "客户 · B店"],
  ["E-A1", "客服 · A店"],
  ["E-A2", "审核员 · A店"],
  ["E-A3", "仓库 · A店"],
  ["E-B2", "审核员 · B店"],
];
const roles: Record<string, string> = {
  customer: "客户",
  support: "客服",
  reviewer: "审核员",
  warehouse: "仓库",
};
type Selection = { kind: string; id: string };
function messageText(message: Message) {
  if (message.role !== "assistant") return message.content;
  // The backend appends authoritative cards for model memory. Keep those in
  // storage; customer-facing cards below already show the actual business data.
  const marker = "\n服务端事实（上下文，勿仿写为最终输出格式）：";
  const index = message.content.lastIndexOf(marker);
  if (index < 0) return message.content;
  try {
    const memory = JSON.parse(message.content.slice(index + marker.length));
    if (
      Array.isArray(memory.cases) &&
      Array.isArray(memory.tickets) &&
      Object.keys(memory).length === 2
    )
      return message.content.slice(0, index);
  } catch {
    // A similarly worded answer is ordinary text, not a serialized memory suffix.
  }
  return message.content;
}
function Notice({ text }: { text: string }) {
  return text ? (
    <p className="notice" role="alert">
      {text}
    </p>
  ) : null;
}
function Status({ value, text }: { value: string; text?: string }) {
  return (
    <span className={`status ${value === "REFUNDED" ? "positive" : ""}`}>
      {text ?? label(value)}
    </span>
  );
}
function Empty({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-mark" aria-hidden="true">
        ↗
      </span>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(storedSession);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [error, setError] = useState("");
  const [user, setUser] = useState("C-A1");
  const [busy, setBusy] = useState(false);
  const api = useMemo(() => (session ? new Api(session) : null), [session]);
  function logout() {
    sessionStorage.removeItem("m5:session");
    setSession(null);
    setIdentity(null);
  }
  useEffect(() => {
    if (!api) return;
    const controller = new AbortController();
    api
      .request<Identity>("/me", undefined, controller.signal)
      .then(setIdentity)
      .catch((e) => {
        if (controller.signal.aborted) return;
        setError(errorText(e));
        if (e instanceof ApiError && e.status === 401) {
          sessionStorage.removeItem("m5:session");
          setSession(null);
        }
      });
    return () => controller.abort();
  }, [api]);
  async function enter() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      setIdentity(null);
      setSession(await login(user));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  if (!session || !api)
    return (
      <main className="login">
        <div className="login-copy">
          <p className="eyebrow">流程 / 售后工作台</p>
          <h1>
            每一步，
            <br />
            都有据可查。
          </h1>
          <p>
            从客户咨询，到人工审核与仓库收货。
            <br />
            在同一条流程里，核对事实，完成交接。
          </p>
          <div className="login-line">
            01 申请　 →　 02 审核　 →　 03 收货　 →　 04 对账
          </div>
        </div>
        <section className="login-form">
          <span className="environment">本地模拟演示</span>
          <h2>进入工作台</h2>
          <p>请选择本次操作身份。每个角色独立登录。</p>
          <label htmlFor="identity">演示身份</label>
          <select
            id="identity"
            value={user}
            onChange={(e) => setUser(e.target.value)}
          >
            {identities.map(([id, name]) => (
              <option key={id} value={id}>
                {name} / {id}
              </option>
            ))}
          </select>
          <button className="primary" onClick={enter} disabled={busy}>
            {busy ? "正在登录…" : "进入工作台 →"}
          </button>
          <Notice text={error} />
          <p className="fine">
            订单、政策与退款均为模拟数据。客户确认后仍须人工审核。
          </p>
        </section>
      </main>
    );
  if (!identity)
    return (
      <main className="loading">
        <h1>正在读取身份与权限…</h1>
        <Notice text={error} />
        <button onClick={logout}>返回身份选择</button>
      </main>
    );
  return (
    <>
      <header className="topbar">
        <a className="brand" href="/">
          流程<span>售后工作台</span>
        </a>
        <span className="environment">
          本地模拟 · {date(identity.business_now)}
        </span>
        <div className="actor">
          <span>
            {identity.tenant_id} /{" "}
            {identity.roles.map((r) => roles[r] ?? r).join("、")} ·{" "}
            {identity.user_id}
          </span>
          <button onClick={logout}>切换身份</button>
        </div>
      </header>
      <Workspace key={session.user_id} api={api} identity={identity} />
    </>
  );
}

function Workspace({ api, identity }: { api: Api; identity: Identity }) {
  const chatAllowed = identity.roles.some((r) =>
    ["customer", "support"].includes(r),
  );
  const [tab, setTab] = useState(chatAllowed ? "orders" : "cases");
  const saved = `m5:selected:${identity.user_id}`;
  const [selection, setSelection] = useState<Selection | null>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(saved) ?? "null");
    } catch {
      return null;
    }
  });
  const [items, setItems] = useState<(Order | Case | Ticket | Conversation)[]>(
    [],
  );
  const [cursor, setCursor] = useState<string | null>(null);
  const [pages, setPages] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const creationLock = useRef(false);
  const [filter, setFilter] = useState("");
  const [revision, setRevision] = useState(0);
  const [mobileDetail, setMobileDetail] = useState(!!selection);
  function select(kind: string, id: string) {
    const value = { kind, id };
    setSelection(value);
    sessionStorage.setItem(saved, JSON.stringify(value));
    setMobileDetail(true);
  }
  const endpoint = `/${tab}?limit=${tab === "orders" ? 20 : 25}${tab === "cases" && filter ? `&status=${filter}` : ""}`;
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    setItems([]);
    setLoading(true);
    setError("");
    async function load() {
      try {
        let next: string | null | undefined = null;
        const all: (Order | Case | Ticket | Conversation)[] = [];
        for (let index = 0; index < pages; index++) {
          const result: Page<Order | Case | Ticket | Conversation> =
            await api.request(
              `${endpoint}${next ? `&cursor=${next}` : ""}`,
              undefined,
              controller.signal,
            );
          all.push(...result.items);
          next = result.next_cursor;
          if (!next) break;
        }
        if (!stopped) {
          setItems(all);
          setCursor(next ?? null);
          setError("");
        }
      } catch (e) {
        if (!stopped) setError(errorText(e));
      } finally {
        if (!stopped) {
          setLoading(false);
          timer = setTimeout(load, 3000);
        }
      }
    }
    void load();
    return () => {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [api, endpoint, revision, pages]);
  function more() {
    setPages((v) => v + 1);
  }
  async function newConversation() {
    if (creationLock.current) return;
    creationLock.current = true;
    setCreating(true);
    setError("");
    try {
      // A new conversation is a new intent. Persist the nonce until success, including refresh/retry.
      const name = `m5:new-conversation:${identity.user_id}`;
      let nonce = sessionStorage.getItem(name);
      if (!nonce) {
        nonce = crypto.randomUUID();
        sessionStorage.setItem(name, nonce);
      }
      const result = await api.request<Conversation>(
        "/conversations",
        {},
        undefined,
        nonce,
      );
      sessionStorage.removeItem(name);
      setTab("conversations");
      select("conversations", result.conversation_id);
      setRevision((v) => v + 1);
    } catch (e) {
      setError(errorText(e));
    } finally {
      creationLock.current = false;
      setCreating(false);
    }
  }
  function itemId(item: Order | Case | Ticket | Conversation) {
    return "conversation_id" in item ? item.conversation_id : item.id;
  }
  return (
    <main className={`workspace ${mobileDetail ? "show-detail" : ""}`}>
      <aside className="list-pane" aria-label="业务列表">
        <div className="list-heading">
          <p className="eyebrow">工作区</p>
          <h1>
            {chatAllowed
              ? "客户与业务"
              : identity.roles.includes("reviewer")
                ? "人工审核"
                : "仓库收货"}
          </h1>
        </div>
        <nav className="tabs" aria-label="业务类型">
          {(chatAllowed
            ? ["orders", "cases", "conversations", "tickets"]
            : ["cases", "tickets"]
          ).map((t) => (
            <button
              key={t}
              aria-current={tab === t ? "page" : undefined}
              onClick={() => {
                setTab(t);
                setFilter("");
                setPages(1);
              }}
            >
              {
                {
                  orders: "订单",
                  cases: "申请",
                  conversations: "会话",
                  tickets: "工单",
                }[t]
              }
            </button>
          ))}
        </nav>
        {tab === "cases" && (
          <label className="filter">
            处理状态
            <select
              aria-label="处理状态"
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value);
                setPages(1);
              }}
            >
              <option value="">全部申请</option>
              {[
                "DRAFT",
                "WAITING_FOR_USER",
                "PENDING_REVIEW",
                "AWAITING_RETURN",
                "READY_TO_REFUND",
                "REFUND_PENDING",
                "MANUAL_INTERVENTION",
                "REFUNDED",
                "REJECTED",
              ].map((s) => (
                <option key={s} value={s}>
                  {label(s)}
                </option>
              ))}
            </select>
          </label>
        )}
        {chatAllowed && (
          <button
            className="new-chat"
            onClick={newConversation}
            disabled={creating}
          >
            {creating ? "正在创建…" : "＋ 新建咨询会话"}
          </button>
        )}
        <Notice text={error} />
        <div className="business-list" aria-busy={loading}>
          {loading ? (
            <p className="list-empty">正在读取业务列表…</p>
          ) : !items.length ? (
            <p className="list-empty">
              暂无{tab === "conversations" ? "会话，点击上方新建" : "相关记录"}
            </p>
          ) : (
            items.map((item) => {
              const id = itemId(item);
              return (
                <button
                  className={`list-row ${selection?.id === id ? "selected" : ""}`}
                  key={id}
                  onClick={() => select(tab, id)}
                >
                  <span className="row-title">
                    {"order_id" in item
                      ? item.order_id
                      : tab === "conversations"
                        ? "售后咨询"
                        : id}
                  </span>
                  <span className="row-meta">
                    {"case_type" in item
                      ? label(item.case_type)
                      : "paid_amount_fen" in item
                        ? money(item.paid_amount_fen)
                        : "category" in item
                          ? label(item.category)
                          : "created_at" in item
                            ? date(item.created_at)
                            : ""}
                  </span>
                  {"status" in item && <Status value={item.status} />}
                  <span className="row-id">
                    {tab !== "orders"
                      ? id.slice(0, 19) + "…"
                      : "查看订单与适用政策"}
                    <span aria-hidden="true">↗</span>
                  </span>
                </button>
              );
            })
          )}
        </div>
        {cursor && (
          <button className="load-more" onClick={more}>
            加载更多
          </button>
        )}
        <footer className="list-footer">
          模拟支付 · 无真实资金流转
          <br />
          业务时间由后端提供
        </footer>
      </aside>
      <section className="detail-pane" aria-label="业务详情">
        <button className="mobile-back" onClick={() => setMobileDetail(false)}>
          ← 返回业务列表
        </button>
        {!selection ? (
          <Empty title="从左侧选择一项业务">
            先核对订单，再开始咨询或处理申请。业务进度会在这里持续更新。
          </Empty>
        ) : selection.kind === "orders" ? (
          <OrderDetail
            key={selection.id}
            api={api}
            id={selection.id}
            onCase={(id) => select("cases", id)}
            onChat={() => {
              void newConversation();
            }}
          />
        ) : selection.kind === "cases" ? (
          <CaseDetail
            key={selection.id}
            api={api}
            identity={identity}
            id={selection.id}
          />
        ) : selection.kind === "conversations" ? (
          <Chat
            key={selection.id}
            api={api}
            id={selection.id}
            onCase={(id) => select("cases", id)}
            onTicket={(id) => select("tickets", id)}
          />
        ) : (
          <TicketDetail key={selection.id} api={api} id={selection.id} />
        )}
      </section>
    </main>
  );
}

function OrderDetail({
  api,
  id,
  onCase,
  onChat,
}: {
  api: Api;
  id: string;
  onCase: (id: string) => void;
  onChat: () => void;
}) {
  const [order, setOrder] = useState<Order | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [error, setError] = useState("");
  const [intent, setIntent] = useState("RETURN_REFUND");
  useEffect(() => {
    const c = new AbortController();
    setPolicy(null);
    api
      .request<Order>(`/orders/${id}`, undefined, c.signal)
      .then(setOrder)
      .catch((e) => {
        if (!c.signal.aborted) setError(errorText(e));
      });
    api
      .request<Policy>(
        `/orders/${id}/policy?intent=${intent}`,
        undefined,
        c.signal,
      )
      .then(setPolicy)
      .catch((e) => {
        if (!c.signal.aborted) setError(errorText(e));
      });
    return () => c.abort();
  }, [api, id, intent]);
  return (
    <div className="detail-content">
      <div className="detail-heading">
        <div>
          <p className="eyebrow">订单详情</p>
          <h1>{id}</h1>
        </div>
        {order && <Status value={order.status} />}
      </div>
      <Notice text={error} />
      {order && (
        <>
          <div className="facts">
            <div>
              <span>实付金额</span>
              <strong>{money(order.paid_amount_fen)}</strong>
            </div>
            <div>
              <span>已模拟退款</span>
              <strong>{money(order.refunded_amount_fen)}</strong>
            </div>
            <div>
              <span>签收时间 · 上海</span>
              <strong>{date(order.delivered_at)}</strong>
            </div>
          </div>
          <div className="section-heading">
            <h2>开始处理</h2>
            <button className="primary" onClick={onChat}>
              新建售后咨询 →
            </button>
          </div>
          <p className="muted">
            在会话中选择这笔订单。默认只咨询；申请或建工单须明确选择操作。
          </p>
          <h2>关联申请</h2>
          {order.cases.length ? (
            order.cases.map((c) => (
              <button
                className="related"
                key={c.id}
                onClick={() => onCase(c.id)}
              >
                <span>{c.id}</span>
                <Status value={c.status} />
                <span>查看 →</span>
              </button>
            ))
          ) : (
            <p className="muted">暂无售后申请。</p>
          )}
          <div className="section-heading">
            <h2>适用政策</h2>
            <select
              aria-label="政策类型"
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
            >
              {["RETURN_REFUND", "DAMAGE_REFUND", "LOGISTICS"].map((t) => (
                <option key={t} value={t}>
                  {label(t)}
                </option>
              ))}
            </select>
          </div>
          {policy && (
            <div className="policy">
              <p className="fine">
                版本 {policy.policy_version} · 后端检索条款
              </p>
              {policy.clauses.map((c) => (
                <article key={c.chunk_id}>
                  <p>{c.text}</p>
                  <small>{c.citation}</small>
                </article>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function CaseDetail({
  api,
  identity,
  id,
}: {
  api: Api;
  identity: Identity;
  id: string;
}) {
  const [item, setItem] = useState<Case | null>(null);
  const [timeline, setTimeline] = useState<Timeline[]>([]);
  const [refund, setRefund] = useState<Refund | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [reason, setReason] = useState("");
  const [returnRequired, setReturnRequired] = useState(true);
  const storage = `m5:confirmation:${api.session.user_id}:${id}`;
  const [confirmation, setConfirmation] = useState<Confirmation | null>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(storage) ?? "null");
    } catch {
      return null;
    }
  });
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const [c, t, r] = await Promise.all([
        api.request<Case>(`/cases/${id}`, undefined, signal),
        api.request<{ items: Timeline[] }>(
          `/cases/${id}/timeline`,
          undefined,
          signal,
        ),
        api.request<Refund>(`/cases/${id}/refund`, undefined, signal),
      ]);
      setItem(c);
      setTimeline(t.items);
      setRefund(r);
    },
    [api, id],
  );
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const c = new AbortController();
    async function tick() {
      try {
        await refresh(c.signal);
      } catch (e) {
        if (!stopped) setError(errorText(e));
      } finally {
        if (!stopped) timer = setTimeout(tick, 1500);
      }
    }
    void tick();
    return () => {
      stopped = true;
      c.abort();
      clearTimeout(timer);
    };
  }, [refresh]);
  async function act(fn: () => Promise<unknown>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(errorText(e));
      await refresh().catch(() => {});
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function summary() {
    if (!item) return;
    const result = await api.request<Confirmation>(
      `/cases/${id}/confirmation`,
      { expected_version: item.version },
    );
    sessionStorage.setItem(storage, JSON.stringify(result));
    setConfirmation(result);
  }
  async function confirmSubmit() {
    if (!confirmation) return;
    await api.request(
      `/confirmations/${confirmation.confirmation_id}/confirm`,
      { payload_digest: confirmation.payload_digest },
    );
    await api.request(`/cases/${id}/submit`, {
      expected_version: confirmation.summary.version,
    });
    sessionStorage.removeItem(storage);
    setConfirmation(null);
  }
  const customer = identity.roles.includes("customer");
  const reviewer = identity.roles.includes("reviewer");
  const warehouse = identity.roles.includes("warehouse");
  const fresh =
    confirmation &&
    item?.version === confirmation.summary.version &&
    item.status === "WAITING_FOR_USER";
  if (!item)
    return (
      <div className="detail-content">
        <Notice text={error} />
        <p>
          {error ? "无法读取该申请，请切换身份或重新选择。" : "正在读取申请…"}
        </p>
      </div>
    );
  return (
    <div className="detail-content">
      <div className="detail-heading">
        <div>
          <p className="eyebrow">售后申请 / {item.order_id}</p>
          <h1>{label(item.case_type)}</h1>
          <p className="resource-id">{item.id}</p>
        </div>
        <Status value={item.status} />
      </div>
      <div className="steps" aria-label="申请流程">
        {["客户确认", "人工审核", "收货（按审批）", "模拟对账"].map(
          (text, i) => (
            <div key={text}>
              <span>0{i + 1}</span>
              {text}
            </div>
          ),
        )}
      </div>
      <Notice text={error} />
      <div className="facts">
        <div>
          <span>申请金额 · 模拟</span>
          <strong>{money(item.requested_amount_fen)}</strong>
        </div>
        <div>
          <span>政策版本</span>
          <strong>{item.policy_version}</strong>
        </div>
        <div>
          <span>申请版本</span>
          <strong>v{item.version}</strong>
        </div>
      </div>
      <h2>客户申请</h2>
      <p className="preserve">{item.reason}</p>
      <p className="fine">
        证据：{item.evidence_refs.join("、") || "未附证据"}
      </p>
      {customer && ["DRAFT", "WAITING_FOR_USER"].includes(item.status) && (
        <section className="action-panel">
          <p className="eyebrow">下一步 / 客户确认</p>
          <h2>核对后，再提交审核</h2>
          {!fresh ? (
            <>
              <p>生成后端确认摘要，核对订单、类型、金额与政策。</p>
              <button
                className="primary"
                disabled={busy}
                onClick={() => void act(summary)}
              >
                生成确认摘要
              </button>
            </>
          ) : (
            <>
              <dl className="summary">
                <dt>订单</dt>
                <dd>{confirmation.summary.order_id}</dd>
                <dt>申请类型</dt>
                <dd>{label(confirmation.summary.case_type)}</dd>
                <dt>申请金额</dt>
                <dd>
                  {money(confirmation.summary.requested_amount_fen)}（模拟）
                </dd>
                <dt>申请原因</dt>
                <dd>{confirmation.summary.reason}</dd>
                <dt>证据</dt>
                <dd>{confirmation.summary.evidence_refs.join("、") || "无"}</dd>
                <dt>政策</dt>
                <dd>{confirmation.summary.policy_version}</dd>
                <dt>摘要有效期至</dt>
                <dd>{date(confirmation.expires_at)} · 业务时间</dd>
              </dl>
              <p className="preserve">{confirmation.summary.notice}</p>
              <button
                className="primary"
                disabled={busy}
                onClick={() => void act(confirmSubmit)}
              >
                {busy ? "正在确认…" : "确认申请并提交审核"}
              </button>
              <button disabled={busy} onClick={() => void act(summary)}>
                重新生成摘要
              </button>
            </>
          )}
        </section>
      )}
      {reviewer && item.status === "PENDING_REVIEW" && (
        <section className="action-panel">
          <p className="eyebrow">下一步 / 人工审核</p>
          <h2>核查后作出决定</h2>
          <label htmlFor="review-reason">
            审核依据
            <textarea
              id="review-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={2000}
              placeholder="填写核验结果与审批理由"
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={returnRequired || item.case_type === "RETURN_REFUND"}
              disabled={item.case_type === "RETURN_REFUND"}
              onChange={(e) => setReturnRequired(e.target.checked)}
            />
            要求退回并由仓库确认收货
          </label>
          <p className="fine">
            普通退货必须收货。损坏申请免退回须由审核员明确决定。
          </p>
          <div className="actions">
            <button
              className="primary"
              disabled={busy || !reason.trim()}
              onClick={() =>
                void act(() =>
                  api.request(`/cases/${id}/review`, {
                    expected_version: item.version,
                    decision: "APPROVE",
                    return_required:
                      item.case_type === "RETURN_REFUND" || returnRequired,
                    reason,
                  }),
                )
              }
            >
              批准申请
            </button>
            <button
              disabled={busy || !reason.trim()}
              onClick={() =>
                void act(() =>
                  api.request(`/cases/${id}/review`, {
                    expected_version: item.version,
                    decision: "REJECT",
                    return_required: true,
                    reason,
                  }),
                )
              }
            >
              拒绝申请
            </button>
          </div>
        </section>
      )}
      {warehouse && item.status === "AWAITING_RETURN" && (
        <section className="action-panel">
          <p className="eyebrow">下一步 / 仓库收货</p>
          <h2>核实退回商品</h2>
          <p>仅在实际模拟收货已核实后操作。收货后进入模拟退款队列。</p>
          <button
            className="primary"
            disabled={busy}
            onClick={() =>
              void act(() =>
                api.request(`/cases/${id}/return-received`, {
                  expected_version: item.version,
                }),
              )
            }
          >
            确认仓库已收货
          </button>
        </section>
      )}
      {item.status === "PENDING_REVIEW" && !reviewer && (
        <p className="waiting">已提交，等待独立审核员处理。</p>
      )}
      {item.status === "AWAITING_RETURN" && !warehouse && (
        <p className="waiting">审核已批准，等待仓库核实退回商品。</p>
      )}
      <section className="refund-panel">
        <div className="section-heading">
          <h2>模拟退款结果</h2>
          <span className="environment">无真实资金流转</span>
        </div>
        {refund?.funds_state === "SUCCEEDED" ? (
          <>
            <p className="refund-result positive">已核对模拟退款成功</p>
            <strong className="amount">
              {money(refund.transaction?.amount_fen ?? 0)}
            </strong>
            <p className="fine">
              模拟支付流水 {refund.transaction?.provider_operation_id}
            </p>
          </>
        ) : refund?.funds_state === "UNKNOWN" ? (
          <>
            <p className="refund-result">处理中 · 结果待对账</p>
            <p>
              当前不能确认模拟退款成功。后台会查询原支付结果；刷新或重启 worker
              后继续恢复。
            </p>
          </>
        ) : (
          <p className="muted">尚未执行模拟退款。</p>
        )}
        {refund?.job && (
          <p className="fine">
            已处理 {refund.job.attempts} 次
            {refund.job.last_error ? " · 上次结果待核查" : ""}
          </p>
        )}
        {reviewer && item.status === "MANUAL_INTERVENTION" && (
          <button
            disabled={busy}
            onClick={() =>
              void act(() =>
                api.request(`/cases/${id}/refund-reconcile`, {
                  expected_version: item.version,
                }),
              )
            }
          >
            请求重新对账
          </button>
        )}
      </section>
      <h2>业务时间线</h2>
      <ol className="timeline">
        {timeline.map((t) => (
          <li key={t.id}>
            <span className="timeline-dot" />
            <div>
              <strong>{eventLabels[t.action] ?? t.action}</strong>
              <p>
                {t.summary.status ? label(t.summary.status) : t.result}
                {t.summary.amount_fen !== undefined
                  ? ` · ${money(t.summary.amount_fen)}`
                  : ""}
              </p>
              <time>{date(t.occurred_at)}</time>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Chat({
  api,
  id,
  onCase,
  onTicket,
}: {
  api: Api;
  id: string;
  onCase: (id: string) => void;
  onTicket: (id: string) => void;
}) {
  const name = `m5:chat:${api.session.user_id}:${id}`;
  const initial = useMemo(() => {
    try {
      return JSON.parse(sessionStorage.getItem(name) ?? "{}") as {
        content?: string;
        order?: string;
        action?: string;
      };
    } catch {
      return {};
    }
  }, [name]);
  const [content, setContent] = useState(initial.content ?? "");
  const [order, setOrder] = useState(initial.order ?? "");
  const [action, setAction] = useState(initial.action ?? "CONSULT");
  const [orders, setOrders] = useState<Order[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    sessionStorage.setItem(name, JSON.stringify({ content, order, action }));
  }, [name, content, order, action]);
  useEffect(() => {
    const c = new AbortController();
    async function load() {
      let next: string | null | undefined = null;
      const all: Order[] = [];
      do {
        const result: Page<Order> = await api.request(
          `/orders?limit=20${next ? `&cursor=${next}` : ""}`,
          undefined,
          c.signal,
        );
        all.push(...result.items);
        next = result.next_cursor;
      } while (next);
      setOrders(all);
    }
    void load().catch((e) => {
      if (!c.signal.aborted) setError(errorText(e));
    });
    return () => c.abort();
  }, [api]);
  useEffect(() => {
    setEvidence([]);
    if (!order) return;
    const c = new AbortController();
    api
      .request<{ items: Evidence[] }>(
        `/orders/${order}/evidence`,
        undefined,
        c.signal,
      )
      .then((v) => setEvidence(v.items))
      .catch((e) => {
        if (!c.signal.aborted) setError(errorText(e));
      });
    return () => c.abort();
  }, [api, order]);
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const c = new AbortController();
    async function tick() {
      try {
        const result = await api.request<{ items: Message[] }>(
          `/conversations/${id}/messages`,
          undefined,
          c.signal,
        );
        if (stopped) return;
        setMessages(result.items);
        const runId = [...result.items].reverse().find((m) => m.run_id)?.run_id;
        if (runId) {
          const [r, e] = await Promise.all([
            api.request<Run>(`/runs/${runId}`, undefined, c.signal),
            api.request<{ items: Event[] }>(
              `/runs/${runId}/events`,
              undefined,
              c.signal,
            ),
          ]);
          if (!stopped) {
            setRun(r);
            setEvents(e.items);
          }
        }
      } catch (e) {
        if (!stopped) setError(errorText(e));
      } finally {
        if (!stopped) timer = setTimeout(tick, 1200);
      }
    }
    void tick();
    return () => {
      stopped = true;
      c.abort();
      clearTimeout(timer);
    };
  }, [api, id, revision]);
  const active = !!run && ["QUEUED", "RUNNING"].includes(run.status);
  async function send() {
    if (lock.current || active || !content.trim()) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const payload = {
        content: content.trim(),
        action,
        ...(order ? { target_order_id: order } : {}),
      };
      const pendingName = `${name}:pending`;
      const fingerprint = JSON.stringify(payload);
      let pending: { fingerprint: string; key: string } | null = null;
      try {
        pending = JSON.parse(sessionStorage.getItem(pendingName) ?? "null");
      } catch {
        pending = null;
      }
      if (!pending || pending.fingerprint !== fingerprint) {
        pending = { fingerprint, key: `ui-${crypto.randomUUID()}` };
        sessionStorage.setItem(pendingName, JSON.stringify(pending));
      }
      const result = await api.request<Run>(`/conversations/${id}/messages`, {
        ...payload,
        client_message_id: pending.key,
      });
      setRun(result);
      sessionStorage.removeItem(pendingName);
      sessionStorage.setItem(
        name,
        JSON.stringify({ content: "", order, action }),
      );
      setContent("");
      setRevision((v) => v + 1);
    } catch (e) {
      setError(errorText(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function cancel() {
    if (!run || lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      await api.request(`/runs/${run.run_id}/cancel`, {});
      setRevision((v) => v + 1);
    } catch (e) {
      setError(errorText(e));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <div className="detail-content chat-detail">
      <div className="detail-heading">
        <div>
          <p className="eyebrow">客户会话</p>
          <h1>先核对，再行动。</h1>
          <p className="resource-id">{id}</p>
        </div>
        {run && (
          <Status
            value={run.status}
            text={
              run.status === "WAITING_FOR_USER" ? "待补充或确认" : undefined
            }
          />
        )}
      </div>
      <Notice text={error} />
      <div className="messages" aria-label="会话消息">
        {!messages.length ? (
          <p className="muted">
            描述问题，并选择需要处理的订单。默认咨询不会修改业务状态。
          </p>
        ) : (
          messages.map((m) => (
            <article className={`message ${m.role}`} key={m.message_id}>
              <small>{m.role === "user" ? "客户输入" : "Agent 回复"}</small>
              <p className="preserve">{messageText(m)}</p>
            </article>
          ))
        )}
      </div>
      {run?.error_code && (
        <p className="notice">
          本轮未完成（{run.error_code}）。请读取业务状态后再决定下一步。
        </p>
      )}
      {run &&
        !active &&
        !["COMPLETED", "CANCELLED", "FAILED"].includes(run.status) && (
          <p className="waiting">请根据回复补充信息，或核对待确认申请。</p>
        )}
      {!!run?.response?.cases?.length && (
        <div className="result-resources">
          <h2>关联售后申请</h2>
          {run.response.cases.map((c) => (
            <button className="related" key={c.id} onClick={() => onCase(c.id)}>
              <span>
                {c.order_id} · {label(c.case_type)}
              </span>
              <span>核对当前状态 →</span>
            </button>
          ))}
        </div>
      )}
      {!!run?.response?.tickets?.length && (
        <div className="result-resources">
          <h2>关联人工工单</h2>
          {run.response.tickets.map((t) => (
            <button
              className="related"
              key={t.id}
              onClick={() => onTicket(t.id)}
            >
              <span>
                {t.order_id} · {label(t.category)}
              </span>
              <span>查看工单 →</span>
            </button>
          ))}
        </div>
      )}
      {!!run?.response?.citations?.length && (
        <details className="citations">
          <summary>本轮政策引用（{run.response.citations.length}）</summary>
          {run.response.citations.map((c, i) => (
            <p className="preserve fine" key={i}>
              {typeof c === "string" ? c : JSON.stringify(c)}
            </p>
          ))}
        </details>
      )}
      <section className="composer">
        <div className="composer-options">
          <label>
            订单
            <select
              aria-label="会话订单"
              value={order}
              onChange={(e) => setOrder(e.target.value)}
              disabled={busy || active}
            >
              <option value="">请选择订单</option>
              {orders.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.id} · {money(o.paid_amount_fen)}
                </option>
              ))}
            </select>
          </label>
          <label>
            本轮操作
            <select
              aria-label="本轮操作"
              value={action}
              onChange={(e) => setAction(e.target.value)}
              disabled={busy || active}
            >
              <option value="CONSULT">仅咨询</option>
              <option value="APPLY_AFTER_SALES">申请售后（先建草稿）</option>
              <option value="CREATE_TICKET">同意建立人工工单</option>
              <option value="SUBMIT_CONFIRMED">提交已确认申请</option>
            </select>
          </label>
        </div>
        <label htmlFor="chat-message">
          问题或补充说明
          <textarea
            id="chat-message"
            placeholder="例如：这笔订单想退货，请先检查适用规则。"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            maxLength={4000}
            disabled={busy || active}
          />
        </label>
        {!!evidence.length && (
          <div className="evidence-picker">
            <span className="fine">可用模拟证据</span>
            {evidence.map((e) => (
              <button
                key={e.id}
                disabled={busy || active}
                onClick={() =>
                  setContent((v) =>
                    `${v}\n证据 ${e.id}：${e.description}`.slice(0, 4000),
                  )
                }
              >
                ＋ {e.id} / {e.kind}
              </button>
            ))}
          </div>
        )}
        <div className="composer-bottom">
          <span className="fine">
            {content.length}/4000 · 修改业务须人工确认与审核
          </span>
          {active ? (
            <button disabled={busy} onClick={() => void cancel()}>
              停止本轮处理
            </button>
          ) : (
            <button
              className="primary"
              onClick={() => void send()}
              disabled={
                busy || !content.trim() || (action !== "CONSULT" && !order)
              }
            >
              {busy ? "正在发送…" : "发送 →"}
            </button>
          )}
        </div>
      </section>
      <details className="trace" open={active}>
        <summary>
          {active ? "正在处理 · 后台任务持续运行" : "本轮可审计步骤"}{" "}
          {events.length > 0 ? `(${events.length})` : ""}
        </summary>
        <ol>
          {events.map((e) => (
            <li key={e.seq}>
              <strong>{eventLabels[e.kind] ?? e.kind}</strong>
              {typeof e.data.name === "string" && (
                <span> · {toolLabels[e.data.name] ?? e.data.name}</span>
              )}
              <time>{date(e.created_at)}</time>
            </li>
          ))}
        </ol>
        <p className="fine">此处展示工具与状态事件。业务结果以申请详情为准。</p>
      </details>
    </div>
  );
}

function TicketDetail({ api, id }: { api: Api; id: string }) {
  const [item, setItem] = useState<Ticket | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    api
      .request<Ticket>(`/tickets/${id}`, undefined, c.signal)
      .then(setItem)
      .catch((e) => {
        if (!c.signal.aborted) setError(errorText(e));
      });
    return () => c.abort();
  }, [api, id]);
  return (
    <div className="detail-content">
      <p className="eyebrow">人工工单</p>
      <h1>{item?.order_id ?? "正在读取…"}</h1>
      <Notice text={error} />
      {item && (
        <>
          <Status value={item.status} />
          <p className="resource-id">{item.id}</p>
          <h2>{label(item.category)}</h2>
          <p className="preserve">{item.summary}</p>
          <p className="waiting">
            等待人工跟进。当前演示仅支持建立和查询工单。
          </p>
        </>
      )}
    </div>
  );
}
