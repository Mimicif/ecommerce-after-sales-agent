# 项目状态与交接

更新时间：2026-10-13（Asia/Shanghai）

## 已完成

- 确定题目、求职目标与第一版范围。
- 编写需求、架构、领域规则、接口、Agent/RAG、评测、开发计划与工程规范。
- 调研企业公开 Agent 工程实践，记录原始来源。
- 提供模拟订单、政策与 36 条评测场景规格。
- M0 工程、uv.lock、配置、真实PostgreSQL 18.6、迁移0001_m0、原子种子导入与显式本地重置。
- 本地开发session（随机token/摘要/到期）、数据库健康检查、最小订单列表/详情与授权过滤。
- 真实PostgreSQL 21项测试通过；真实HTTP健康与双租户/跨客户隔离冒烟通过。
- M1统一只读服务、Clock注入、物流/有效政策接口、资格前检、5个只读工具与实际JSON Schema。
- schema0002_m1为已发布政策rules/clauses增加内容摘要并保留旧数据；工具在数据库只读事务中执行。
- M0/M1合计109项测试通过（规则/合同/真实PostgreSQL）；M1真实HTTP及M0 HTTP回归通过，Alembic无schema差异。
- M2草稿/证据授权、活动申请约束、摘要/客户确认/提交、人工审核/仓库、退款任务与模拟支付查询恢复、工单和审计。
- M0–M2最终206项测试通过；真实HTTP超时未知→新worker恢复、重复执行与M0/M1回归通过；两笔模拟退款各唯一流水。
- M3 DeepSeek-V4.1-Flash / LangGraph单Agent、十个工具、PG会话/run/事件/checkpoint、worker租约与恢复；M0–M3共245项测试通过，M3新增39项。
- 8个成功真实模型run及1个保留的初次格式失败trace；完整客户独立确认后提交、物流工单、损坏证据澄清及双租户验收通过。M0/M1/M2 HTTP回归、Alembic差异与只读业务对账通过。
- M4中文keyword检索/授权条款索引、可核查事实声明、36场景执行器、两批各24条人工核验样本与基线评测；全量293项测试通过（M4新增48）。
- prompt-v5最终开发Agent 51/51；第二批独立Agent 36/36、可核查事实217/223（97.3%）、引用有效率100%、P95 9.203秒；全部硬约束零违规，机器门槛PASS。首批27/33失败原样保留，第二批未用于调优；自由文本引用支撑不足另有语义复核记录。
- M5 React + TypeScript流程工作台、六个授权只读发现接口、独立客户/客服/审核/仓库、后端摘要确认、轮询/刷新/网络未知/取消恢复；308项回归、2项真实浏览器测试通过。5个live run完成三段剧本，另2个取消run；3笔模拟退款=3笔提供方操作，总64700分，开发库状态不变。OpenAPI/工具/冻结M4实现对账PASS。
- M6源码交付、干净依赖安装、新物理PostgreSQL数据库和生产前端验收通过；聊天记忆后缀展示修复、checkpoint-v2-m6保存顺序修复及三项新增PG回归。311项完整后台回归、两项浏览器测试、5个live run、3唯一模拟退款64700分通过；录屏228.2秒，临时库清理、开发库不变，机器核验PASS。原失败和M4/M5成绩保留。

## 未完成

M0–M6本地MVP已完成；没有线上服务、生产认证或真实支付。自由文本引用只能部分核验：N12一条回复在承认流程条款缺失后仍使用笼统的收货前置表述，已记录辅助语义复核，不声称100%语义正确。
M4完整成绩独立存放evals/reports，不把离线结果记作真实模型成绩；首批独立失败转为暴露回归后，不能再当作泛化成绩。

## 下一步

当前可按README启动本地工作台，使用dist源码包和独立录像交接；用户已于2026-10-13授权公开同步到GitHub，发布记录见下方。后续真实集成/生产认证/公网部署需另定范围。M5同标签页sessionStorage恢复，长会话仅最近50条；没有证据上传或生产认证。
模型或状态检查实现改变须重新回归并更新评测暴露范围；第二批冻结实现哈希已记录。没有pgvector需求证据，保留keyword检索。模型失败后仍须读取业务真相。

## 里程碑

| 阶段 | 状态 | 通过证据 |
|---|---|---|
| 文档与规格 | 已完成 | 文件清单与结构验证；尚无业务运行证据 |
| M0 工程骨架 | 已完成 | 21项真实PostgreSQL测试；迁移/重置/重复导入；真实HTTP隔离冒烟；artifacts/m0/ |
| M1 业务规则与只读工具 | 已完成 | M0/M1共109项测试；7天/48小时/政策与权限边界；只读事务阻断写操作；artifacts/m1/ |
| M2 写入、确认、审核、模拟退款 | 已完成 | 共206项测试（M2新增97）；真实HTTP、超时/崩溃/并发/记账回滚、唯一流水；artifacts/m2/ |
| M3 单 Agent 与恢复 | 已完成 | 245项测试（M3新增39）；8成功live run、初次失败修复保留；独立确认后提交/物流工单/补问/隔离；artifacts/m3/ |
| M4 RAG、基线与评测 | 已完成 | 293项回归；开发51/51、新独立36/36、事实97.3%、引用100%、P95 9.203秒；零硬违规、验收PASS；docs/16及artifacts/m4 |
| M5 前端与演示 | 已完成 | 308项回归、2浏览器测试、5live run、3剧本/3唯一模拟退款、开发库不变、机器PASS；docs/17及artifacts/m5 |
| M6 打包与验收 | 已完成 | 干净安装/生产构建/新物理库迁移及重复seed；311后台回归、2浏览器测试、5live run、3唯一模拟退款；228.2秒录像、源码清单/哈希及机器PASS；docs/18及artifacts/m6 |

## GitHub 开源发布（2026-10-13）

用户明确授权公开同步，并确认 `Mimicif/ecommerce-after-sales-agent` 与 MIT。新增 LICENSE、克隆和开源范围说明、ADR-021及docs/20_OPEN_SOURCE.md；.gitignore扩展排除环境变体、视频与私钥。发布本地分支codex/open-source，远端main；使用GitHub noreply提交邮箱。

保留源码、锁文件、模拟数据、测试与已检查的历史评测/验收证据；不上传模型密钥、数据库/运行时、依赖、视频或dist压缩包。1253个发布文件凭据检查、文档/fixture结构与1116个受验收源码文件哈希检查通过；本次未重跑PostgreSQL回归、浏览器或live模型评测。应用/API/schema/prompt/policy/eval不变；原M6源码包及证据不覆盖，历史“未上传”记录描述当时状态。

已成功发布至 https://github.com/Mimicif/ecommerce-after-sales-agent 。首次源码提交 `1a5fd8f50dcb7178156cde7d6055604b5ffe349a` 与远端main一致，公开可见性与默认main分支已核对，GitHub许可证接口识别为MIT。原Git/libcurl直连两次失败，通过一次性loopback桥接、Python HTTPS转发标准Git协议完成非强制推送；临时服务已关闭，凭据未保存，不改变系统代理或TLS设置。随后提交本发布记录。

## 每次后续开发结束时更新（字段）

- 本次实际完成的阶段与代码。
- 安装、启动、迁移、种子和测试命令。
- 操作系统、模型、依赖锁版本。
- 真实执行结果与证据位置；没有运行的检查明确写未运行。
- 失败与剩余风险。
- 下一步最小可执行任务。
- 规则或接口变更及对应决策记录。

## M5 本次交付（2026-10-12）

用户确认“左侧业务列表，右侧详情与时间线”。已实现本地React工作台、独立角色session、持久化run事件轮询与客户后端摘要卡。按钮确认后确定性提交，不把按钮写入冒充Agent执行；原SUBMIT_CONFIRMED模型路径保留。只读发现接口不放宽写权限。C剧本改用O-A108，避免复用已完成O-A101；ADR-018记录原因与合同影响。

真实PostgreSQL全量308 passed（311.17秒），两项Edge浏览器测试通过（83.013秒）；5个真实deepseek-flash run，另2个取消run不计live。普通149元、损坏399元、超时恢复99元，3笔模拟支付和本地流水唯一，总64700分，开发业务状态前后相同。窗口1366×900及390×844、键盘、刷新/双击/网络回执中断/HTML文本均通过；两份浏览器脚本初次失败报告保留，验收以最终报告为准。

版本：API/api-v1-m5、应用/前端0.6.0，Python/uv锁升级工程版本；Node24.14.1/npm11.11.0、React19.3.0、TypeScript7.0.2、Vite8.3.4、Playwright1.64.0、Prettier3.9.10固定npm锁。schema0005_m4、模型/十工具/prompt及fixtures/policy/eval不改；M4冻结四文件哈希仍一致。Git分支codex/m5，尚未提交或上传。

启动：四终端分别scripts/backend.ps1 serve（fixture时钟）、agent-worker -Watch（相同clock）、worker -Watch及scripts/frontend.ps1 dev。http://127.0.0.1:5173。复现命令、角色和限制见README与docs/17；原开发库保留历史数据，全新三剧本用scripts/browser_m5.py在after_sales_test自己的UUID schema，不重置开发库。

证据：artifacts/m5/pytest.xml、browser_results.json、browser_trace.json、browser_workflows.json、browser_recovery.json、browser_database.json、verification.json及桌面/手机/超时截图。TypeScript生产构建、格式、Ruff、合同对账、文档链接检查通过。M6干净安装、交付打包、录屏尚未开始；没有SSE、证据上传、生产鉴权或真实支付。

本会话已核对并替换旧0.5 API（原PID37260）为0.6 API，127.0.0.1:8000；前端5173和Agent/refund常驻worker已启动，启动前确认开发库活动run/job均0。代理健康、登录、me身份与业务时钟冒烟PASS，见artifacts/m5/local_preview.json。受管理exec会话：API58646（实际PID21272）、Agent35513、refund63041、前端85017；后续不要重复启动占用端口的服务，停服务仅针对本项目这些会话。

## 已接受的默认设定

独立目录、模拟电商单店业务、保留两个测试租户、单件整单售后、人工审批退款、Windows本地开发。
这些属于本项目产品设定，不是法律条文或企业通用标准。

## M0 本次交付与运行记录

用户已于2026-10-11明确授权M0编码并选择项目内独立PostgreSQL；AGENTS.md的初始文档阶段限制由本次请求启动编码。
Git已在本项目初始化，分支codex/m0；没有提交、上传或修改旧项目。

环境：Windows / Python3.12.7（D:/anaconda3/python.exe）/ uv0.12.0 / Git2.54.0.rc1.windows.1；Docker命令不在PATH，本次未使用Docker。
PostgreSQL18.6存于.runtime/pgsql与.runtime/pgdata，127.0.0.1:55432，应用用户非superuser；开发/测试库隔离。
中文路径initdb报UTF8错误，采用ASCII目录联接解决：C:/Users/32370/.codex/visualizations/2026/10/11/01a12af4-b7e0-75d1-acda-a885ced20f35/pg-runtime。
联接配置已保存在.runtime/pg-runtime-alias；未来可用setup_postgres.ps1 -RuntimeAlias重新指定可用ASCII路径。

依赖锁：uv.lock；主要版本FastAPI0.143.0、SQLAlchemy2.0.54、Alembic1.20.0、psycopg3.3.6、Pydantic2.14.0、pydantic-settings2.15.0、Uvicorn0.54.0、pytest9.1.1。
版本：API api-v1-m0，schema 0001_m0，fixtures-v1，policy-schema-v1及原3个policy版本；eval源场景不变，prompt/tool/model未实现。

实际命令：

~~~powershell
uv sync --locked --python 'D:/anaconda3/python.exe' --cache-dir .runtime/uv-cache
./scripts/setup_postgres.ps1 setup
./scripts/backend.ps1 migrate
./scripts/backend.ps1 seed
./scripts/backend.ps1 reset -Target after_sales_dev
./scripts/backend.ps1 seed
$env:PYTHONPATH = Join-Path (Get-Location).Path 'backend'
./.venv/Scripts/python.exe -m alembic check
./.venv/Scripts/python.exe -m pytest --junitxml=artifacts/m0/pytest.xml
./scripts/backend.ps1 serve
# 另一个终端：
./.venv/Scripts/python.exe scripts/smoke_m0.py --output artifacts/m0/http_smoke.json
./.venv/Scripts/ruff.exe check backend scripts/smoke_m0.py
./.venv/Scripts/ruff.exe format --check backend scripts/smoke_m0.py
./scripts/validate_handoff.ps1
~~~

实测：21 passed，14.63s，1条Starlette/httpx弃用警告；HTTP smoke PASS；Alembic无schema差异；导入14订单、8身份、2租户、2物流、1证据、3政策，重复导入already_imported。
确认过期session与跨租户/跨客户访问失败、伪造身份无效、审核/仓库角色禁止查单；并发空库导入只成功一次，坏政策外键导致整个导入回滚。
初期安装受到执行sandbox网络限制，经工具授权后完成依赖下载与本地数据库连接；无需用户更改系统权限。
证据：artifacts/m0/pytest.xml、http_smoke.json、verification.json；API文档与实际运行说明见README。
限制：M0开发鉴权只适合本地模拟；没有生产鉴权、模型、退款逻辑或业务规则成绩。后续升级Starlette测试客户端前检查其httpx迁移警告。

## M1 本次交付与运行记录

用户于2026-10-12授权M1；先定义docs/13_M1_ACCEPTANCE.md，新增ADR-014澄清阶段、Clock、政策完整性与只读工具合同。
Git分支codex/m1；未提交/上传，未修改旧项目。分支切换首次自动审批超时，一次重试成功，未留下阻碍。
复用Python3.12.7/PostgreSQL18.6及原依赖锁版本；项目版本0.2.0，uv.lock同步根项目版本，没有新增或升级依赖。
版本：api-v1-m1、tools-v1-m1、domain-v1-m1、schema0002_m1；fixtures-v1/policy-schema-v1及policy原3版本、36场景源数据不变；prompt/model/live eval未实现。

业务：客户/客服统一授权服务；最新物流>48h/EXCEPTION为可能异常，无/未来轨迹为未知；常规退货按本租户窗口含边界，缺失/未来签收、特殊品类、历史部分退款转人工；零余额阻断；损坏不套常规窗口拒绝，全部人工判断。
政策先SQL过滤tenant/status/time；冲突、缺失、缺条款、规则冲突或rules/clauses漂移失败关闭。摘要仅证明内容未漂移，不证明任意文本语义。M1按intent返回条款及引用，不对query做相关度检索。
工具每次重新读取可信actor的数据库身份、独立session并SET TRANSACTION READ ONLY；参数错误在数据库操作前拒绝，不允许指定身份、时间、金额、SQL/URL/路径。数据库失败不伪造业务成功。

实际命令（项目根PowerShell）：

~~~powershell
./scripts/setup_postgres.ps1 start
./scripts/backend.ps1 migrate
./scripts/backend.ps1 seed
$env:PYTHONPATH = Join-Path (Get-Location).Path 'backend'
./.venv/Scripts/python.exe -m pytest -q --junitxml=artifacts/m1/pytest.xml
./.venv/Scripts/python.exe -m alembic check
$env:BUSINESS_CLOCK_MODE = 'fixture'
./scripts/backend.ps1 serve
# 另一个终端：
./.venv/Scripts/python.exe scripts/smoke_m1.py --output artifacts/m1/http_smoke.json
./.venv/Scripts/python.exe scripts/smoke_m0.py --output artifacts/m1/m0_http_regression.json
./.venv/Scripts/ruff.exe check backend scripts/smoke_m0.py scripts/smoke_m1.py
./.venv/Scripts/ruff.exe format --check backend scripts/smoke_m0.py scripts/smoke_m1.py
./scripts/validate_handoff.ps1
~~~

结果：109 passed，50.61s，1条原有Starlette/httpx弃用警告；真实HTTP M1/M0 PASS；Alembic "No new upgrade operations detected"；导入already_imported，不重置开发数据。
首轮测试105例中1例的O-A109预期金额误写11900，按原fixture10900修正，新增路径校验和权限覆盖后109例全通过；没有为过测修改fixtures。
证据：artifacts/m1/pytest.xml、http_smoke.json、m0_http_regression.json、verification.json；实际工具schema docs/contracts/m1_tools.json。
限制：M1不创建售后、确认、工单或退款；活动case检查与损坏描述/证据校验等待M2。M1元数据条款读取不等于M4 RAG或真实Agent评测。当前服务以fixture时钟运行，仅127.0.0.1。

## M2 本次交付与运行记录

用户明确请求“M2继续”，在原M1基础继续编码。分支codex/m2；未提交或上传仓库，没有修改旧项目。先定义 [M2验收条件](docs/14_M2_ACCEPTANCE.md) 和ADR-015，再实现最小确定性后端。

版本：应用0.3.0、API api-v1-m2、schema0003_m2、规则domain-v1-m2。现有五个只读工具保持tools-v1-m1；写工具/Agent编排为M3工作。fixtures-v1、policy-schema-v1、政策三版本及36评测规格源文件不变；锁文件只更新工程版本，没有升级依赖。

实现：
- 真实数据库的case/confirmation/review/job/ledger/provider-operation/idempotency/ticket/audit表；租户复合FK、活动申请部分唯一索引、唯一任务/流水、金额与版本约束。
- 写入复用服务端身份、订单→case→job锁顺序、版本比较和同事务幂等记录；成功重放保留原响应，当前状态用GET。确认摘要绑定金额/政策摘要/订单及申请版本，锁后取Clock；编辑失效、15分钟边界、消费确认失败回滚。
- 客户与客服创建/提交；客户owner独立确认；同租户reviewer审核且不能批准自己创建的申请；普通退货必须warehouse确认收货，损坏由人工明确是否退回。
- 持久化worker独立短事务领取任务、30秒租约/令牌、5秒重试、3次失败转人工；先查同一操作键，支付调用在业务事务外；模拟结果独立事务保留。成功后崩溃或本地记账失败可查询恢复；订单与唯一流水同事务记账。
- 物流/人工工单创建读取；成功/阻断/恢复审计不含原因正文、证据内容、令牌或原始SQL异常。数据库无法接受阻断审计时不能保证落库，仍返回原错误。

运行（项目根PowerShell）：

~~~powershell
./scripts/setup_postgres.ps1 start
./scripts/backend.ps1 migrate
./scripts/backend.ps1 seed
$env:BUSINESS_CLOCK_MODE = 'fixture'
./scripts/backend.ps1 serve
# 另开终端：
./scripts/backend.ps1 worker
./.venv/Scripts/python.exe scripts/smoke_m2.py
./scripts/backend.ps1 test
./.venv/Scripts/python.exe scripts/export_contracts.py
./.venv/Scripts/python.exe scripts/verify_m2.py
~~~

真实验证：
- 最终全套206 passed / 0 failed / 0 skipped，205.26秒；M0 21、M1 API/工具63、M1规则25、M2 97。一条既有Starlette/httpx弃用警告；未替换依赖掩盖。
- 普通退货O-A101模拟14900分、超7天损坏O-A103模拟8900分，真实HTTP完成客户确认/提交、独立人工审核、普通退货仓库收货；成功后超时仍UNKNOWN，新的CLI worker查询恢复，两笔唯一成功流水，共23800分。第二次HTTP演示和重复worker不增加退款金额。
- 并发草稿/提交/审批、两worker、旧租约回写、同键支付并发；跨客户/租户、角色撤销、自审、证据归属、禁止参数；确认过期/摘要漂移/锁后时钟、资金与状态守卫均通过。
- 新schema全新迁移、M2 downgrade/upgrade保留M1种子；Alembic check无差异；重复seed返回already_imported且保留售后数据。
- 实际OpenAPI/read-tool合同导出一致，Ruff与格式检查通过。证据：[最终验收JSON](artifacts/m2/verification.json)、[pytest](artifacts/m2/pytest.xml)、[首次HTTP](artifacts/m2/http_smoke.json)、[重复HTTP](artifacts/m2/http_repeat.json)。

开发修正记录：首轮75通过/1失败，是误把正常可退O-A102列为不可申请样本；修正测试，未改fixtures。追加约束时开发库暂存空M2表的旧迁移缺少唯一约束，校准只作用于经检查为空的M2表，M1数据保留。M2完成后O-A103已全额退款，M1冒烟原“损坏转人工”断言不再适用，已按真实余额区分“已退款不可再次申请”和“未退款损坏需人工”；前后HTTP回归均留存，未重置数据制造通过。

限制：模拟供应商使用同一个PostgreSQL中独立事务验证崩溃边界，不是外部支付服务。人工工单首版只有OPEN创建/读取；提交后的取消/变更仍人工处理。fixture时钟冻结，不能当真实确认有效期展示；正式演示真实时间可用system模式，但订单资格随真实日期变化。模型、prompt、live Agent评测及前端未实施。
当前API运行127.0.0.1:8000，业务Clock=fixture；退款任务需显式运行worker CLI，没有后台常驻调度服务。

## M3 本次交付与运行记录

用户授权M3并选择DeepSeek V4.1 Flash；2026-10-12官方核验model_id=deepseek-flash，密钥仅本项目.env。先定义docs/15_M3_ACCEPTANCE.md并记录ADR-016，再实现单LangGraph、PG持久化会话/运行/事件/checkpoint、10个有限工具和供应商HTTPX适配。Git分支codex/m3；未提交/上传，未修改旧项目或私人配置。
版本app0.4.0、api-v1-m3、schema0004_m3、tools-v1-m3、prompt-v1-m3；domain-v1-m2/fixtures-v1/policy-schema-v1/36场景源数据不变。锁定langgraph1.2.14/checkpoint4.2.0/langchain-core1.6.9，沿用HTTPX0.28.1。thinking disabled、temperature0、max_tokens1536，明确禁用LangSmith tracing，不保存隐藏推理。

默认CONSULT只读；写入要求客户action和target_order_id匹配，复用M2真实客户确认。45秒/8模型/12工具预算，15秒租约令牌，模型和工具结果缓存、稳定业务幂等键；写效果/结果/事件同事务。WAITING_FOR_USER新消息开新run，进程恢复继续原run，取消run不删除业务资源。

实际验证：245 passed / 0 failed/errors/skipped，258.56秒（M3新增39）；三个崩溃位置、并发、跨用户/租户、参数与权限、预算、脱敏、虚假状态/引用均通过。M0/M1/M2 HTTP回归、迁移roundtrip/无schema差异、重复seed、Ruff/format与文档检查通过。M3 live 8成功run，另1初次格式错误trace保留并已修复；C-A2/O-A108新的完整独立确认后提交流程通过。真实模型20调用/21工具调用，59741tokens；含一次能力探针61518tokens，官方价格区间估算USD0.00549519–0.01099038。
首次提交已成功但模型误输出额外状态卡字段，严格合同返回MODEL_RESPONSE_INVALID；修正三字段输出与历史记忆格式，读取现有申请恢复，未重建/退款。业务真相由后端GET判断。现O-A102/39900分、O-A108/9900分均PENDING_REVIEW且无退款任务/流水；M2两个唯一模拟退款仍合计23800分。M1冒烟改为接受并校验该活动申请，未重置种子掩盖结果。

运行：`./scripts/backend.ps1 migrate`/`seed`/`serve`；消息入队后另开fixture终端执行`./scripts/backend.ps1 agent-worker`，批次结束即退出。15秒租约过期后重启恢复原run，deadline不重置。完整命令与消息body见README和M3报告。
证据：[M3对账](artifacts/m3/verification.json)、[245项测试](artifacts/m3/pytest.xml)、[真实模型](artifacts/m3/live_clean.json)、[初次失败](artifacts/m3/live_initial_failure.json)。只读复核`./.venv/Scripts/python.exe scripts/verify_m3.py`；导出m3_openapi/m3_tools，历史M2合同/报告保留。verify_m2.py是M2冻结阶段检查，升级后使用verify_m3.py。

M3验收时API为M3，127.0.0.1:8000，fixture业务时钟；以上为保留的历史交接。M4验收时升级app0.5.0，同地址运行、没有前端/常驻调度；当前M5已升级0.6、实现前端与常驻worker，仍无生产鉴权或真实支付。

## M4 验收交接（2026-10-12）

结果见[验收报告](docs/16_M4_ACCEPTANCE.md)、[机器核验](artifacts/m4/verification.json)、[真实HTTP](artifacts/m4/http_smoke.json)、[语义限制](artifacts/m4/qualitative_review.json)。所有门槛通过后才将M4标记完成。开发库原两笔模拟退款总额23800分及待审申请保持，评测在after_sales_test临时schema中执行。

首批人工冻结集27/33（81.8%）失败保留在evals/reports/holdout_release；用户选择修复并补新集。第二批holdout_v2已人工冻结数据与实现hash，三次真实模型成绩不用于调优。B0第二批33/36，B1只读23/24，同样只读子集B2为24/24；不声称Agent在固定流程上普遍胜出。

M4历史启动使用README本地步骤；可信重建索引`./scripts/backend.ps1 index-policies`，模型worker为`./scripts/backend.ps1 agent-worker`。全量回归`./scripts/backend.ps1 test`；M4当时的verify_m4.py绑定0.5实际合同，当前0.6使用verify_m5.py，不重新覆盖历史M4报告。M0–M4合同/报告保留，当前合同为docs/contracts/m5_openapi.json与m5_tools.json。


## M6 开发与交付记录（2026-10-12验证，2026-10-13交接）

先定义docs/18_M6_ACCEPTANCE.md完成条件，再开始源码打包、干净依赖安装、全新独立物理数据库和生产前端三剧本录屏。README与架构按ADR-019修正早期计划描述。应用/API/schema/prompt/tool/policy/eval版本不变；M4四文件冻结哈希不改。

首轮候选源码包干净安装、生产构建、迁移检查和两次seed成功；307项回归通过，1项test_reset_guard因验收进程全局fixture时钟与测试关闭DEV_MODE冲突而失败。不是业务守卫缺陷；修正为pytest默认system、演示fixture。artifacts/m6_initial_clock_failure保留完整报告与XML，临时库已清理。


M6重录进展：用户已确认修复仅展示层的内部记忆后缀，前端修复已完成；干净构建/新数据库再次通过，网络/文本安全检查通过。但第一项live流程暴露checkpoint pending write早于父checkpoint提交的外键竞态（草稿已创建，run FAILED，无重复退款）。用户明确选择修复竞态并继续验收，ADR-020记录checkpoint-v2-m6短事务释放锁后有界等待方案。真实PG强制顺序测试修复前失败；修复后7项checkpoint测试通过，含3条新增回归。第三轮失败及诊断归档artifacts/m6_checkpoint_race_failure。前一轮完整后台308 passed及旧录屏保存在artifacts/m6_before_display_fix，原M4/M5证据保留。

最终第四轮：从candidate4源码包创建全新venv/node_modules（复用下载缓存），锁文件安装、生产构建、PostgreSQL18.6新物理库迁移/Alembic check/两次seed全部通过。311 passed / 0 failed / 0 errors / 0 skipped，342.53秒；不复用旧后台成绩。两项生产Edge浏览器测试通过（242.957秒），5个真实deepseek-flash run及2个取消run，三申请REFUNDED、3唯一模拟退款=3提供方操作、合计64700分。超时UNKNOWN→新worker查询恢复、刷新/重复操作、跨用户/租户与角色隔离、网络回执丢失、客户原文/HTML文本、390px/键盘均通过，开发库快照不变，临时物理库已清理。

最终录像228.2秒，1366×900，SHA256 bf711d410cf8a0d6bd8979452ab15980323356e154242e1c0753690f0f54889f；复核聊天正文无内部后缀、超时待对账与恢复画面正确。verify_m6机器PASS，1124个被验收核心文件哈希未变，四个M4冻结文件/数据集、OpenAPI/十工具一致；新组件checkpoint-v2-m6单独记录hash，不把历史M4成绩扩大到新持久化组件。

交付：dist/after-sales-agent-0.6.0-local-m6.zip、配套.sha256与.verification.json；录像artifacts/m6/demo.webm独立交付。启动和复现见README，docs/18/19及artifacts/m6保存证据。2026-10-13续接时原进程已退出，已恢复独立PG/API/两个worker/Vite，8000健康与5173 HTTP200；managed session分别81614/33562/14151/77590。Git仍codex/m6，未提交或上传。限制仍为本地模拟MVP，不含生产认证、真实支付/部署/图片上传；未新增独立模型泛化评测。
