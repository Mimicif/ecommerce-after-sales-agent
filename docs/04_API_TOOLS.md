# API与工具契约 v1.0

本文件是开发合同。M5 API版本api-v1-m5 / 应用0.6.0，数据库保持0005_m4，十个模型工具保持tools-v2-m4。实际HTTP schema见 [m5_openapi.json](contracts/m5_openapi.json)，M2–M4历史合同保留。
认证从已验证token或session取得身份；不能相信请求body中的角色或tenant字段。
前缀/api/v1。任何资源ID都必须做服务端权限检查。

### M5 工作台只读发现接口

- `GET /me`：已验证user_id、tenant_id、roles、business_now（UTC）、simulated；身份和业务时间不接受客户端覆盖。
- `GET /cases`：cursor/limit（1..50，默认25）、可选有限status；客户本人订单资源、员工本租户资源。
- `GET /tickets`：cursor/limit同上，权限同原单工单查询。
- `GET /conversations`：cursor/limit同上，仅customer/support本人会话；员工不能从列表枚举客户会话。
- `GET /orders/{id}/evidence`：customer/support按原订单权限，返回订单客户在本租户的模拟证据id/kind/description；无上传接口。
- `GET /cases/{id}/timeline`：按原申请权限返回审计action/result/occurred_at/summary，按时间及ID排序；不返回身份令牌、原始敏感日志或隐藏推理。

列表ID升序分页，未知参数422；跨所有者/租户资源404。原订单分页最大20及全部写权限不变。详情与退款由原后端接口驱动；独立客户确认按钮使用后端摘要、稳定幂等键和expected_version，不能由模型构造金额或审批结果。版本/过期/网络未知由错误提示及重新读取状态处理。

### M0 已实现合同

`POST /api/v1/dev/sessions` 只接受 `{ "user_id": "C-A1" }`，额外字段422。
DEV_MODE + 实际 loopback peer 才开放；响应201，data含 access_token、token_type、expires_at、user_id、tenant_id、roles、simulated。
后续带 `Authorization: Bearer <token>`；token只在创建响应中出现，数据库保存摘要，过期返回401。
关闭DEV_MODE或非本地调用登录返回404，已有开发token也不可使用。
健康路径为 `/api/v1/health`，探测数据库，数据库不可达返回503 / DATABASE_UNAVAILABLE。
订单分页采用 `cursor`（上一页最后一个ID）、`limit`（1..20），data含 items 和 next_cursor。
仅customer/support可查询；reviewer/warehouse返回403；他人或其他租户资源返回404。
M0订单响应仅包含ID、品类、状态、整数分金额、UTC签收时间、version。
所有响应含ok/code/data/trace_id，验证错误不回显输入，数据库异常不返回堆栈。

### M1 已实现合同

- `GET /orders/{id}/logistics`：返回订单状态、最新时间、最多100条轨迹（时间/ID倒序）、events_truncated、possible_exception（true/false/null）、manual_required、reason_codes、evaluated_at。
- `GET /orders/{id}/policy?intent=RETURN_REFUND&query=...`：intent限RETURN_REFUND/DAMAGE_REFUND/LOGISTICS，query最大500字符。只返回本租户唯一当前PUBLISHED版本的适用intent和ALL条款、版本、有效期、引用。retrieval_mode固定metadata_only；M1不对query排名。
- `POST /orders/{id}/eligibility`：body仅case_type（RETURN_REFUND/DAMAGE_REFUND）和可选reason_code（CHANGE_OF_MIND/DAMAGED/OTHER，默认OTHER）。reason_code不能覆盖类型/规则。
- eligibility.data含eligibility、reason_codes、refundable_amount_fen（当前剩余金额，非批准金额）、policy_version、order_version、evaluated_at、assessment_scope=READ_ONLY_PRECHECK、review_required=true。
- 无有效政策/冲突/缺条款/无效规则/发布内容漂移：政策接口503/POLICY_UNAVAILABLE并给MANUAL_REVIEW；资格接口200且manual_required、policy_version=null，保留具体原因码。实际数据库读取失败503/DATABASE_UNAVAILABLE，不能伪装为政策缺失、无轨迹或正常结果。
- 客户/客服授权同M0；所有资源先核验权限再读物流/政策，跨客户/租户404。ID最大64字符且只含大写字母、数字、连字符。新接口拒绝now/tenant/金额/未知字段。
- 默认业务时钟system；可信配置BUSINESS_CLOCK_MODE=fixture在DEV_MODE读取seed_imports.fixture_clock；时钟未导入503/CLOCK_UNAVAILABLE。session到期仍用真实UTC。

资格仍为只读前检，不能当作资金授权。M2已增加活动case查询，存在非终态申请返回manual_required/ACTIVE_CASE_EXISTS；所有写入口仍在订单锁内重新校验。

### M2 已实现合同

所有写接口需要 `Idempotency-Key: <8..128字符>`，字符限字母数字与 `._:-`。按租户、身份、操作及资源保存请求摘要与成功响应，同键异参409；重试先核验当前身份/权限。幂等重放返回原成功响应，当前业务状态使用GET重新读取。禁止body额外字段，整数版本严格拒绝浮点/字符串/bool。

| 路径（前缀/api/v1） | body |
|---|---|
| POST /cases/drafts | order_id、case_type、reason（1..2000）、evidence_refs（最多20，不可重复，默认[]） |
| PATCH /cases/{id}/draft | expected_version、reason、evidence_refs；DRAFT/WAITING可编辑，回到DRAFT，版本+1 |
| POST /cases/{id}/confirmation | expected_version；仅客户owner，重新计算并展示摘要，版本+1 |
| POST /confirmations/{id}/confirm | payload_digest（后端生成的64位hex摘要）；只记录真实客户确认，不推进提交 |
| POST /cases/{id}/submit | expected_version；后台查对应客户确认，事务内消费并推进PENDING_REVIEW |
| POST /cases/{id}/cancel | expected_version；仅客户owner，可取消DRAFT/WAITING |
| POST /cases/{id}/review | expected_version、decision（APPROVE/REJECT）、reason、return_required（bool） |
| POST /cases/{id}/return-received | expected_version；仅warehouse，必须已批准且须退回 |
| POST /cases/{id}/refund-reconcile | expected_version；reviewer请求恢复/查询任务，不执行退款或写成功；活跃租约返回409 |
| POST /tickets | order_id、category（LOGISTICS/MANUAL_AFTER_SALES）、summary（1..2000） |

GET /cases/{id}返回ID/订单/类型/真实状态、原因/证据引用、后端金额/政策/版本及simulated。customer仅自己的订单；support/reviewer/warehouse仅本租户。GET /cases/{id}/refund返回funds_state（NOT_EXECUTED/UNKNOWN/SUCCEEDED）、job摘要和已记账模拟流水；未知不能显示退款成功。GET /tickets/{id}按同样资源归属授权；创建工单不执行退款。

确认摘要包含申请版本、订单版本、原因/证据、政策版本与内容摘要、整数分金额、人工审批说明。15分钟使用可信业务Clock；取得业务锁后重新读取时间，now>=expiry失效。编辑或摘要外变化使digest/版本失效。客服草稿由真实客户owner生成摘要并确认，support可以在确认后提交。

常规不满足规则、损坏未签收/部分退款等返回409/MANUAL_REVIEW_REQUIRED，next_action=CREATE_SUPPORT_TICKET；缺政策返回503/POLICY_UNAVAILABLE与人工提示，不自动虚构工单。损坏描述和至少一个归属客户的模拟证据引用必需，不鉴定真伪。普通退款批准必须return_required=true；员工不能批准自己创建的申请。

批准/收货在同一事务创建唯一退款job。CLI worker执行任务，客户API没有资金执行入口。默认模拟成功；可信CLI的fault支持timeout_before/timeout_after/unavailable。30秒租约、5秒重试间隔、最多3次失败转MANUAL_INTERVENTION；授权恢复保持同一操作键。退款规则采用批准快照，执行/记账仍检查订单版本与余额。所有模拟结果单独事务持久化，不能当作真实支付接口。

## HTTP接口

| 方法与路径 | 角色 | 核心行为 |
|---|---|---|
| POST /dev/sessions | 仅本地开发模式 | 从固定演示用户获取短期session；非开发模式关闭 |
| GET /health | 任意 | 存活状态；不返回凭据 |
| GET /orders | customer/support | 只列有权订单，分页 |
| GET /orders/{id} | customer/support | 订单脱敏详情 |
| GET /orders/{id}/logistics | customer/support | 轨迹或明确错误 |
| GET /orders/{id}/policy | customer/support | M1按授权租户、有效期、intent返回政策条款 |
| POST /orders/{id}/eligibility | customer/support | M1只读申请前检，不能提交或批准 |
| POST /conversations | customer/support | 绑定身份 |
| POST /conversations/{id}/messages | owner | client_message_id去重，创建持久化run，返回202与run_id |
| GET /runs/{id} | owner/support授权 | run状态 |
| GET /runs/{id}/events?after_seq= | 同上 | 顺序、脱敏事件，供轮询 |
| POST /cases/drafts | customer/support | 创建草稿，计算金额和规则，不提交审核 |
| PATCH /cases/{id}/draft | 同上 | 仅草稿，version比较，旧确认失效 |
| POST /cases/{id}/confirmation | customer owner | 创建确认摘要，返回confirmation_id、expires_at |
| POST /confirmations/{id}/confirm | customer owner | 校验版本与身份，记录客户确认 |
| POST /cases/{id}/submit | owner/support授权 | Idempotency-Key及有效确认，提交审核 |
| GET /cases/{id} | 资源授权角色 | 返回真实状态 |
| POST /cases/{id}/review | reviewer | expected_version、decision、reason、return_required |
| POST /cases/{id}/return-received | warehouse | 核对AWAITING_RETURN后推进 |
| POST /cases/{id}/refund-reconcile | reviewer | 仅请求恢复/对账，不能跳过审核或直接成功 |
| GET /cases/{id}/refund | 资源授权角色 | 模拟流水和未知状态 |
| POST /tickets | customer/support | 创建本租户物流/人工工单，幂等 |
| GET /tickets/{id} | 资源授权角色 | 工单状态 |

确认接口不可暴露为LLM工具。审核、收货与对账同样不向LLM开放。
支持客服draft但客户确认须由订单owner执行；演示时切换独立客户session。

## Agent工具白名单

M3十个工具均已实现。真实模型工具JSON Schema见 [m3_tools.json](contracts/m3_tools.json)，历史 [M1只读合同](contracts/m1_tools.json) 保留。
`app.tools.ReadTools`由可信Python后端上下文构造（session factory、已验证actor_id、Clock），不暴露给客户端一个“选择任意actor”的接口。
每次调用独立session、重新读取数据库身份、PostgreSQL READ ONLY事务，异常关闭/回滚该事务；新调用不会复用已失败的事务。
工具统一返回ok/code/data/retryable/trace_id；参数非法与未知工具INVALID_ARGUMENT，禁止字段不回显；查询错误DATABASE_UNAVAILABLE/retryable=true。M3新增tool_version，trace_id绑定run。写工具复用M2事务与规则，并将效果、幂等记录、调用结果和事件在同一事务提交。

| 名称 | 模型输入 | 输出 | 副作用 |
|---|---|---|---|
| list_my_orders | cursor、limit（最大20） | 授权订单摘要 | 无 |
| get_order | order_id | 订单状态、金额、版本 | 无 |
| get_logistics | order_id | 轨迹、更新时间、异常标记 | 无 |
| search_policy | order_id、intent、query | 有效政策片段与引用 | 无 |
| check_eligibility | order_id、case_type、reason_code | eligible/manual_required/reason_codes/amount_fen/policy_version | 无 |
| create_case_draft | order_id、case_type、reason、evidence_refs | draft与计算摘要 | 草稿写入 |
| get_case | case_id | 状态及下一步 | 无 |
| submit_case | case_id、expected_version | 已确认申请或明确阻断 | 提交写入 |
| create_support_ticket | order_id、category、summary | ticket_id与状态 | 工单写入 |
| get_support_ticket | ticket_id | 状态 | 无 |

tenant、actor、时钟、confirmation查询、operation key从可信执行上下文注入。
工具不接受任意SQL、HTTP URL、文件系统路径或自由代码。
create_case_draft仅在用户表达售后处理意图且已认证action/target_order_id匹配时调用。默认CONSULT不能创建草稿或工单，模型不能改变可信action。

### M3 会话与运行合同

`POST /conversations` body为`{}`，需要Idempotency-Key，绑定当前客户/客服，返回201/conversation_id。
`POST /conversations/{id}/messages` body为`client_message_id`（8..128，字母数字及`._:-`）、`content`（1..4000）、`action`（默认CONSULT）、`target_order_id`（可选授权订单）；返回202/run。
写入意图分别APPLY_AFTER_SALES、CREATE_TICKET、SUBMIT_CONFIRMED，写工具还要求选定target_order_id。请求不能设置tenant、actor、金额、时间、model或run状态。所有未知字段422。
同client_message_id和body返回原run及其当前状态；同键异参409/IDEMPOTENCY_CONFLICT。会话有QUEUED/RUNNING时另一消息409/RUN_ACTIVE。WAITING_FOR_USER已完成当前轮，可以接新消息；不会后台自动确认。
`GET /conversations/{id}/messages` 返回最近50条按seq升序的脱敏消息；`GET /runs/{id}` 返回状态/版本/预算使用/错误/服务端事实卡；`GET /runs/{id}/events?after_seq=0&limit=100` 返回单run顺序事件和next_cursor。客户仅自己会话，support只读本租户；发消息及取消只能owner。reviewer/warehouse不能使用聊天入口。
`POST /runs/{id}/cancel` body为`{}`，重复取消返回当前状态，撤销run租约；不取消已创建case或工单。重复接口调用无须新的业务写入。
独立`agent-worker`领取QUEUED或过期RUNNING；15秒租约、45秒不重置deadline、最多8模型和12工具调用。每条消息独立run，历史只取本会话最近12条。真实模型失败返回FAILED和安全错误码，业务写入可能已成功，必须GET当前资源再决定下一步。
最终模型JSON仅answer/needs_input/citations。HTTP response额外cases/tickets由后端刷新生成；禁止模型伪造金额卡或审批卡。新错误包括ACTION_NOT_AUTHORIZED、TARGET_ORDER_REQUIRED、TARGET_ORDER_MISMATCH、RUN_ACTIVE、RUN_LEASE_LOST、RUN_BUDGET_EXCEEDED、TOOL_CORRECTION_EXHAUSTED、MODEL_RESPONSE_INVALID、MODEL_TIMEOUT、MODEL_AUTH_FAILED、MODEL_BALANCE_INSUFFICIENT、CITATION_UNVERIFIED、UNVERIFIED_STATUS_CLAIM。

## 统一结果示例

~~~json
{
  "ok": false,
  "code": "CONFIRMATION_REQUIRED",
  "retryable": false,
  "data": {"case_id": "CASE-001", "next_action": "CUSTOMER_CONFIRM"},
  "trace_id": "TRACE-001"
}
~~~

成功结构同样包含ok、code、data、trace_id；错误不返回栈、密钥、完整地址。
JSON schema限制枚举、长度、ID格式、额外字段；错误不得通过把ok改为true掩盖。
check_eligibility.data固定包含eligibility（eligible / ineligible / manual_required）、reason_codes、refundable_amount_fen、policy_version、order_version。允许申请与允许退款是两个不同结论；eligible不得转为已批准。

## 错误码

M4补充：GET订单详情在授权后返回最近五条cases（id/status/version），用于查售后进展；列表的cases默认空，不能由模型猜申请ID。政策HTTP增加top_k=1–6（默认3），query最长500；工具top_k仍严格整数，HTTP查询参数允许字符串数字转换。返回retrieval_mode=keyword_v1、排名candidates及完整规则摘要rule_summary。检索失败不伪造条款，POLICY_INDEX_STALE由POLICY_UNAVAILABLE的reason_codes说明。

M4历史合同见contracts/m4_openapi.json与m4_tools.json；当前M5合同见m5_openapi.json与m5_tools.json。十个业务工具与可信action、target_order_id、客户独立确认守卫保持。模型最终新增facts，POLICY版本ID允许小写v后缀；工具资源参数格式未放宽。FACT_UNVERIFIED/CITATION_UNVERIFIED/MODEL_RESPONSE_INVALID失败停止，业务写入可能已完成，仍应读取后端真实状态。

RESOURCE_NOT_FOUND、UNAUTHORIZED、FORBIDDEN、INVALID_ARGUMENT、VERSION_CONFLICT、
IDEMPOTENCY_CONFLICT、ACTIVE_CASE_EXISTS、CONFIRMATION_REQUIRED、CONFIRMATION_EXPIRED、
POLICY_UNAVAILABLE、MANUAL_REVIEW_REQUIRED、INVALID_STATE_TRANSITION、
PROVIDER_TIMEOUT、PROVIDER_UNAVAILABLE、RUN_BUDGET_EXCEEDED、DATABASE_UNAVAILABLE、CLOCK_UNAVAILABLE。

资格不满足作为明确业务结果返回，不能全部变成500。

M6持久化补充（ADR-020，checkpoint-v2-m6）：pending writes在父checkpoint尚未提交时释放run锁后短暂等待，每次重新核验租约和预算；最多2秒后安全失败RUN_CHECKPOINT_NOT_READY，run为FAILED，HTTP资源结构不变。该错误不代表业务工具未写入，仍须GET已有申请/工单，不自动发起新的业务操作。租约失效仍为RUN_LEASE_LOST。M5接口/工具合同保持一致，当前交付证据使用verify_m6.py。

聊天展示仅隐藏assistant末尾可识别的cases/tickets内部记忆后缀；存储消息和HTTP内容保持原样，结构化业务状态卡仍按后端资源读取。客户原文不裁剪。
HTTP建议：schema错误422；鉴权401；角色禁止403；无权资源404；版本/状态/幂等冲突409；供应商不可用503。
超时后写状态未知时保留业务资源，避免前端重发为新操作。

## 成功提交示例

~~~json
{
  "case_id": "CASE-001",
  "expected_version": 2
}
~~~

请求头带Idempotency-Key。后端查客户确认并核对digest、expiry、case版本、订单owner与金额。
返回原case_id和PENDING_REVIEW；不能返回REFUNDED。
同幂等键相同body返回相同结果；不同body返回409。
