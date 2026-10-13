# 架构决策记录

## ADR-018：M5 流程工作台与独立角色确认（2026-10-12，已采纳）

用户选择左侧业务列表、右侧详情与时间线。采用 React + TypeScript + Vite，本地同源代理仅允许 loopback API；消息与业务进度轮询，不提前引入 SSE。新增身份、申请/工单/本人会话列表、订单证据与申请审计时间线为只读发现接口；租户/所有者来自已验证 session，分页和过滤参数不能提供身份。客户只读本人资源，员工按已有本租户资源权限；会话列表仅本人，不改变原写权限。

旧演示稿写“客户点击确认，Agent提交”。本阶段客户确认卡由后端生成完整摘要，客户显式点击后前端依次调用独立确认和确定性提交接口。这是同一次客户授权的可审计执行，仍须后端验证摘要、版本、有效期、权限和幂等；减少已确认申请对模型可用性的依赖。Agent 的 SUBMIT_CONFIRMED 路径保留，模型仍不能确认、审核、收货或退款。修改11演示稿明确两种路径，不能将按钮行为称为模型执行。

刷新恢复使用角色隔离的 sessionStorage 会话选择、未完成消息请求及确认摘要。session 是本地短期令牌，真实供应商密钥留在后端。写请求持久稳定键和在途锁，网络未知后复用键；后端状态是最终依据。退款未知显示处理中，成功仅取已入账的后端流水。支付故障只通过可信本地 CLI 注入，不增加用户 HTTP 故障入口。

三段连续演示不能复用已退款的 O-A101 再退款。C改用 C-A2 的 O-A108（99元），在 after_sales_test UUID schema 中实测超时和新worker恢复；原开发库已有流水不重置。fixtures/policy/schema/prompt/model/eval保持M4版本，API/应用/frontend升级 api-v1-m5 / 0.6.0；工具仍 tools-v2-m4。影响04/11/17、实际OpenAPI、列表权限测试与浏览器验收；证据由17报告记录。

## ADR-017：M4 中文检索、可核查事实与公平评测（2026-10-12，已采纳）

M1明确把相关度检索留到M4。本阶段在当前租户/发布状态/有效期/intent SQL过滤后，用中文领域词、同义词和二字词项BM25排序，默认top-k=3（1–6）。真实PostgreSQL建立policy_chunks及tenant/version/intent索引，与当前已验证clauses逐字核对；漂移失败关闭。规则判定继续读取完整结构化规则，排名不改变规则。当前语料只有数条条款，没有向量检索需求证据，暂不引入pgvector。

原S15/S16/S18首句未授权建工单，与ADR-016的CONSULT只读冲突。用户选择“增加客户明确同意转人工的第二轮，再验证实际工单”；以request_contracts.json补充可信客户输入，原36场景oracle不变。S34同样须明确授权后建核查工单。sidecar只包含输入动作、目标和后续话语，不含答案；执行器不按case_id实现业务或评分。HOLDOUT_REVIEW列24条新oracle，用户已人工核验同意冻结，sha256及确认记录见holdout_freeze.json。

查售后进展需要实际case ID，因此授权get_order返回最近五条关联申请的ID/status/version；未授权订单仍不可读取。模型最终facts声明金额、时间、资格、物流等断言，后端验证成功工具来源（含严格类型和时区等值）。另检查阿拉伯数字金额/完整日历日期及常见状态主张；这是有边界的语义防护，不能声称覆盖所有自然语言。政策ID事实允许小写v；业务工具资源ID约束不放宽。真实模型初试暴露零累计退款被误当完成，修正为仅对已由facts核查的“已退款0元/分”免除完成状态匹配。

每例after_sales_test独立UUID schema；真实迁移、种子、HTTP身份操作和持久化worker，模拟支付仍独立事务。规则/API共享一次；B0固定表单、B1同供应商七个只读工具在问答子集、B2完整十工具各适用自然语言案例三次，不选择最好一次。S35循环模型只计FAULT_CONTRACT。oracle只在执行后传入评分器。报告保存全部失败、分母、来源、token/成本和活动时间；不用B1写任务失败证明Agent更好。

用户明确授权将项目模拟订单/物流/政策/工单发送至api.deepseek.com进行M4评测，真实客户数据仍未授权；不发送身份令牌，密钥只用于HTTP鉴权。没有真实live结果或未达门槛时不标记M4完成。版本app0.5.0、schema0005_m4、tools-v2-m4、prompt-v5-m4、keyword_v1、eval-v2-m4；保留历史M0–M3合同/报告与开发数据。

开发试验发现auto工具阶段启用JSON mode可能生成文本工具标记，不能把文本解析成有权限的调用；保留原生工具选择。格式/事实/引用失败最多一次纯回复修复，工具列表为空且后端禁止任何修复阶段工具调用，使用JSON mode；同一8模型调用/45秒预算及持久化回放。保留每次模型输出和FINAL_REPAIR事件，再失败停止。prompt-v4明确申请动作已授权草稿，无需再次聊天授权；资料缺失才补问。诊断只存异常类型，不存原始异常/栈/密钥。24条冻结集以固定v4首轮验收，不以其失败调整prompt。

首轮冻结集27/33（81.8%）未达门槛，用户明确要求“继续修复，并补新的独立验收集重新核验”。上段“不以其失败调整prompt”仅描述首轮固定v4运行；之后首批转为暴露回归集，保留失败成绩。v5对不可重试POLICY_UNAVAILABLE追加可信后端提示，已授权CREATE_TICKET可直接建人工核查单，不能建售后草稿；具体订单退货问题必须调用资格前检。状态文本检查区别否定/未来条件与已完成主张，并加入负向测试确保真正完成主张仍受状态守卫。第二批holdout_v2共24条已由用户重新人工核验冻结，记录数据与prompt/Agent/模型适配/状态检查实现哈希；实现改变须新评测核验，当前集不能继续充当独立集。未跑完/未达门槛不宣布M4完成。

## ADR-016：M3 单Agent、明确意图与恢复（2026-10-12，已采纳）

用户选定DeepSeek V4.1 Flash，官方核验对应deepseek-flash；使用https://api.deepseek.com/chat/completions，thinking=disabled、temperature=0、max_tokens=1536。HTTPX已锁定，直接实现官方HTTP协议，不增加OpenAI SDK或供应商平台抽象。价格与来源记录在M3报告；别名可能随供应商更新，响应model和核验日期一起记录。

API消息body增加action（默认CONSULT，另有APPLY_AFTER_SALES/CREATE_TICKET/SUBMIT_CONFIRMED）。这是已认证客户明确选择操作的合同，不能由模型设置；自然语言意图仍由模型理解，但不能代替写授权。仅咨询和否定/转折不授权写。M5将提供相应用户操作；M3测试driver使用同一字段。客户确认仍只由M2独立接口提供，聊天“已确认”不是后端确认。

实现时补充target_order_id：写工具必须匹配已认证客户选择的订单，缺失返回TARGET_ORDER_REQUIRED、不匹配TARGET_ORDER_MISMATCH；入队前验证该订单权限。原因是action仅限制操作类型，仍不足以阻止模型在多个候选中自行挑选订单。此字段不进入模型工具参数，也不能设置金额或客户确认。

一个消息一个持久化run；WAITING_FOR_USER为已完成当前轮、等待新客户输入的状态，新消息创建新run并读取本会话最近12条脱敏消息。崩溃恢复继续同一个run的LangGraph checkpoint；不会把等待新输入误当作需自动执行的任务。取消run不取消已创建业务申请。

采用BaseCheckpointSaver的小型PostgreSQL适配，完整state与pending writes受同一run租约令牌保护，所有表由Alembic迁移；只支持本项目单图/空namespace，不构建通用checkpoint服务。需要此适配以在同一事务核验运行租约，阻止旧worker覆盖新checkpoint；不使用内存持久化或SQLite。图状态只存安全JSON，不反序列化任意Python对象。

模型/工具调用单独持久化，按run+逻辑步骤缓存；写工具稳定键与M2幂等记录、执行结果同事务提交。run行锁期间仅访问本地业务数据库，不等待模型。模型调用在事务外，结果落库和checkpoint写入再次核验租约。45秒deadline不因重启重置；15秒租约、单次模型请求最多10秒，节点之间续租；8模型/12工具预算包含重试，工具错误最多一次修正。

聊天文本在入库前脱敏；事件记录模型/输入输出引用、版本、usage/latency、有效工具参数摘要与结果/来源，不保存reasoning_content或原始敏感日志。关闭LangSmith tracing。业务状态与金额由后端刷新生成卡片；无后端依据的资金成功/批准等声明拒绝返回。模型自由说明仍需M4语义评测，不能把少量live验收当成36场景成绩。

真实调用曾在提交已成功后把状态卡复制进最终JSON，导致MODEL_RESPONSE_INVALID。保留失败trace；最终模型合同严格限answer/needs_input/citations三字段，历史assistant记忆改为简短说明及显式上下文事实，不仿写卡片输出格式。引用只接受本轮search_policy结果；状态断言由已观察且刷新后的业务状态核对。重试读取已提交资源，不重新建单。

版本目标：app0.4.0、api-v1-m3、tools-v1-m3、prompt-v1-m3、schema0004_m3；领域/fixtures/policy/eval沿用已验收版本。M2历史合同保留。

## ADR-015：M2 事务与本地模拟支付（2026-10-12，已采纳）

草稿编辑仅改原因/证据，订单/类型不能换；WAITING_FOR_USER 编辑回到 DRAFT 并递增版本。客户可取消 DRAFT/WAITING_FOR_USER。所有写接口要求 Idempotency-Key（8..128字符），幂等范围为租户+身份+操作及资源；请求规范摘要不同返回409，成功响应保存在同一事务。重试仍核验当前角色与资源访问，再返回原成功响应。

确认使用可信业务 Clock（本地 fixture 模式为演示冻结时间）；session、worker 租约/重试使用真实 UTC。确认摘要包含版本、政策内容摘要与订单版本。缺有效政策、损坏未签收、部分退款历史无法形成可支付申请，返回转人工工单提示；损坏超退货窗口/特殊品类可进入独立人工审核，但不能绕过证据/政策/余额约束。审批重新验证当前规则，批准后固定规则/金额快照。

事务按订单→case→job加锁；幂等 advisory transaction lock 序列化同键请求，活动case部分唯一索引覆盖所有非终态。退款 job 领取独立短事务 SKIP LOCKED，执行再次按上述顺序锁定并核验租约令牌；网络调用在事务外。租约失效后旧 worker 不可回写。

模拟支付结果单独事务持久化在 PostgreSQL 的 simulated_provider_operations，模拟独立外部结果与本地记账之间的崩溃边界，不声称真实供应商集成。operation_key由case固定派生；先查询，未有结果才发起。同键同金额返回原结果，金额冲突失败。故障仅可信 CLI/测试注入，不是客户参数；默认成功，支持成功后超时、提交前超时、不可用。三次尝试后人工介入，授权对账恢复同键，绝不由请求直接标记成功。

支付结果与订单/批准金额不符时保留人工介入与活动约束；确认未知资金仍处于处理中。审计仅记录状态/版本/金额摘要，不保存原因正文、证据内容、令牌或个人信息。M2先实现 REST 和确定性驱动，M3接入写工具与 Agent；没有未实现的工具占位模块。

版本：api-v1-m2、schema0003_m2、domain-v1-m2；M1五个只读工具合同保持 tools-v1-m1，M3才扩展。fixtures/policy/eval保持原版本。验证证据见 M2 验收报告与 PROJECT_STATUS。

更新日期：2026-10-13；状态：已采纳；M0–M6实施与验收证据见PROJECT_STATUS.md；GitHub公开同步由ADR-021记录用户授权。

| ID | 决策 | 理由 |
|---|---|---|
| ADR-001 | 独立新目录，原项目不修改 | 确保定位清晰和交接安全 |
| ADR-002 | 三类首发售后，单件整单模拟退款 | 控制个人项目规模并能验证完整闭环 |
| ADR-003 | 模型理解/工具选择，代码控制规则/资金/权限 | 限制模型错误造成业务写入 |
| ADR-004 | 客户确认 + 全部退款人工审核 | 客户同意不等于商家批准 |
| ADR-005 | FastAPI + PostgreSQL单体 | 事务和并发证据比平台复杂度重要 |
| ADR-006 | M3用LangGraph单Agent | 便于显式编排与恢复；不替代业务幂等 |
| ADR-007 | 先中文词项检索，向量按评测增加 | 小型政策库先证实复杂度收益 |
| ADR-008 | 持久化job + stable key + query/reconcile | 演示真实超时和崩溃语义 |
| ADR-009 | 框架、模型、prompt、policy、schema、eval各自版本化 | 可定位回归并复现实验 |
| ADR-010 | 先后端/评测后前端 | 避免只有聊天壳而没有可验证业务 |
| ADR-011 | demo identities仅DEV_MODE与本地使用 | 便于演示角色，同时保留隔离验证 |
| ADR-012 | 模拟政策不当作法律条款 | 区分项目设定与真实业务义务 |

## 变更要求

变更时写：背景、备选方案、采纳方案、影响到哪些合同/测试、验证证据和日期。
原决策不直接抹掉，标记superseded并指向替代记录。
具体模型与依赖版本仍待M0/M3实际验证，不等于项目未明确总体技术方向。

## ADR-013：M0 本地数据库与鉴权实现（2026-10-11）

背景：Windows 已有 Python 3.12.7、uv 0.12.0、Git 2.54.0.rc1.windows.1；未发现 Docker 或 PostgreSQL。用户选择在项目内下载独立 PostgreSQL。
备选：系统安装、Docker、已有数据库；采纳 `.runtime/pgsql` + `.runtime/pgdata`，仅 127.0.0.1:55432，不注册 Windows 服务。
数据库使用 SCRAM 密码，应用角色非 superuser；开发和测试数据库分别为 after_sales_dev / after_sales_test。

鉴权采纳 256-bit 随机 opaque token + 数据库存储 SHA-256 摘要，真实 UTC 短期到期，身份每次从数据库读取。
修正 08 文档“生成与签名”的笼统描述：服务端随机令牌并查询摘要同样实现 session 验证，无需再引入 JWT/签名密钥；不会接收客户端 tenant/roles。
开发登录与 session 使用同时要求 DEV_MODE 和实际 loopback peer；标准启动器关闭 proxy headers。

M0 为隔离验收提前提供最小 `/api/v1/orders` 和 `/api/v1/orders/{id}`，分页最大20；不提前提供物流、资格引擎或模型工具。
政策以 policy.json 的版本化 rules/clauses 完整导入，policy.md 仅对照保留；避免把说明段落与其他租户混在一起索引。
schema 版本为 0001_m0；API 为 api-v1-m0；fixture、policy、eval 源数据版本保持原值；prompt/tool/model 尚未实施。
影响：04/08、M0合同、README、数据库迁移与 PostgreSQL 集成测试；实测结果统一记录在 PROJECT_STATUS.md。

## ADR-014：M1 规则与只读服务（2026-10-12）

背景：M1需要确定性规则、工具合同与错误路径；M0尚无售后case/写业务，B租户政策仅提供3天窗口和全审核。
备选：提前建立M2空模块、让模型补政策字段、现在构建完整RAG；均会扩大阶段或把未实现内容当作事实。
采纳：统一只读服务复用身份授权；M1资格判断可查询，但不作为正式写入授权，活动case守卫随M2真实case表加入，届时所有写入口重新校验。
损坏始终manual_required；M1不自动鉴定证据或创建工单。全局签收/品类/审批/部分退款约束来自领域代码，政策必须提供正整数退货窗口与all_refunds_require_review=true，缺少这些核心字段失败关闭。B不缺省出未经定义的商家规则。

Clock默认system（真实UTC），可信本地配置BUSINESS_CLOCK_MODE=fixture或测试注入FixedClock提供冻结时间；fixture模式要求DEV_MODE，读取seed_imports.fixture_clock。规则一次请求使用一次now；session到期继续真实UTC。
物流按最新轨迹判定（同时间以ID排序），>48小时才标记可能异常；无/未来轨迹为未知并需人工；失败返回错误，不伪装为空列表或丢件。
政策先做租户/发布/有效期SQL筛选，再读取条款；零个或多个当前版本失败关闭。M1按intent返回所有适用条款（含ALL），query不做语义或相关度检索；M4再实现中文keyword与top-k。

发布完整性：schema0002_m1增加policy_versions.content_digest，迁移为现有版本计算rules+clauses的规范JSON摘要；导入同时写摘要，读取时验证。单独修改规则/条款导致POLICY_UNAVAILABLE。摘要用于检测发布后内容漂移，不声称能证明任意自然语言语义与规则完全一致；首次模拟语料按现有已采纳规则核对，后续政策发布须另行做一致性验收。
政策正文不能改变权限；人工审核/仓库收货/资金执行仍无模型工具。工具参数不接收身份、时间、金额、任意SQL、URL或路径；每次调用重新从数据库取身份并在只读事务中执行。
影响：03/04/05、M1合同、迁移、seed与Clock配置、领域/API/工具测试；API api-v1-m1，工具tools-v1-m1，schema0002_m1，规则domain-v1-m1；fixtures/policy/eval源数据不修改，prompt/model未实现。


## ADR-019：M6 可复现本地源码交付（2026-10-12）

背景：M5已验收，M6需要干净安装、全新数据库和录屏；早期架构仍写向量检索与一个worker，README保留前端未开始及旧合同校验命令。
采纳：按ADR-017保留keyword检索，按已实现CLI明确Agent与退款两个worker。README改为当前0.6.0启动与只读历史证据导航，保留旧阶段报告，不重跑覆盖。
交付使用显式源码路径清单、每文件SHA256和ZIP摘要，排除.env/数据库/依赖/原始日志；从候选源码包解压新目录并按两个锁文件安装，创建独立物理after_sales_m6_UUID数据库验收生产构建。完整pytest仍按其安全合同只在after_sales_test创建独立schema。
本阶段应用/API/schema/prompt/tool/policy/eval版本不变，M4冻结实现不改；只参数化浏览器验收路径/端口/生产预览/录像，修复迁移失败时清理流程。最终补入的交付文档和证据必须核验与候选代码哈希一致，不以文档更新为由重跑同一完整测试。
影响：README、架构、M6脚本、浏览器测试配置与交付报告；不引入公网服务、真实数据或支付，不自动提交/上传。


### ADR-019 补充：录屏复核后的聊天展示修复

用户确认仅修复展示层并重录。Agent.finish会给存储消息附加cases/tickets作为下一轮模型记忆；模型最终answer与结构化申请卡已有独立字段，前端把整段存储内容展示造成内部说明混入正文。
采纳仅裁剪assistant的可识别合法记忆后缀；用户输入及不匹配普通文本保留。后端HTTP/模型记忆/API schema和冻结四文件不改，避免以展示修复改变评测实现。新增真实浏览器断言并重录，已有完整后台回归以源文件集合和锁文件哈希一致为沿用条件；前后报告和录像分别保留。

## ADR-020：M6 checkpoint 父子提交顺序修复（2026-10-12）

背景：重录在草稿已成功写入后触发graph_writes父checkpoint外键错误；LangGraph分别调度两个后台保存future，run行锁不能保证父记录先提交。用户明确授权修复竞态并继续验收。

采纳：checkpoint-v2-m6在每次短事务中重新核验run租约/预算并查询父checkpoint；父记录尚未提交时释放run行锁，再最多等待2秒。父记录存在才写pending writes；超时安全失败RUN_CHECKPOINT_NOT_READY，过期租约拒绝写入。保留外键、唯一键和既有负索引覆盖语义，不创建空父记录、不忽略异常、不延长run预算。

验证：真实PostgreSQL强制write先于parent；修复前同一测试外键失败，修复后通过；另测无父记录超时无孤儿，以及等待过程中租约失效。重新从干净源码包执行311项完整回归、真实模型三剧本和录屏。第三轮失败永久保留artifacts/m6_checkpoint_race_failure。

版本范围：应用/API/schema/工具/prompt/模型配置不变，持久化组件新增checkpoint-v2-m6及完整源码SHA256。M4四个冻结文件与数据集仍逐一核验，但原成绩仅对应当时实现；修复后的持久化不冒称新的独立模型评测。M5历史报告不覆盖，当前交付使用verify_m6.py。

## ADR-021：GitHub 公开源码与 MIT 许可证（2026-10-13，已采纳）

背景：用户明确请求“同步当前项目开源到我的github上”，并确认仓库名 `Mimicif/ecommerce-after-sales-agent` 与 MIT 许可证。本次明确授权创建公开仓库、提交与推送；此前“默认本地交付、不自动上传”仍是一般约定，本次按用户发布请求执行。

备选：仅上传源码压缩包、将全部本地产物直接纳入 Git、公开可复现源码与已脱敏证据。采纳第三种：保留当前实现、锁文件、模拟数据、测试、历史评测和失败证据；排除 `.env` 及变体、运行时、数据库、依赖、视频、私钥与交付压缩包。MIT 适用于本项目原创内容，第三方依赖保留各自许可证。

新增 LICENSE、README 克隆说明和公开范围、docs/20_OPEN_SOURCE.md；补强 .gitignore，使用 GitHub noreply 提交邮箱。原本地 M6 源码包与历史验收文件不覆盖；本次仅发布准备，不变更 API/schema/prompt/policy/eval 或业务逻辑，也不声称重新运行真实模型评测。历史 verify_m6 要求本地录像与原候选源码哈希（含旧 .gitignore），克隆仓库不能直接当作该历史交付包。

验证：拟发布文件按实际本地密钥/密码比对，并检查通用供应商令牌、Bearer、JWT、JSON 凭据及私钥；只输出文件名和结论，不输出凭据。文档链接/fixtures/scenarios 校验与受验收源码哈希比对，发布后核对远端 main 提交、公开可见性和 MIT 识别。发布详情见20文档和PROJECT_STATUS。
