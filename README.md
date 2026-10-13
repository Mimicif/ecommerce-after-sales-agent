# 电商售后工单处理 Agent

本地模拟售后业务：单 Agent 查询订单、物流、适用政策，澄清信息、创建草稿或人工工单；客户确认、人工审核、仓库收货和模拟退款由确定性后端分别校验。应用0.6.0、API api-v1-m5、schema0005_m4、checkpoint-v2-m6。M0–M6已验收，见[项目状态](PROJECT_STATUS.md)和[M6验收](docs/18_M6_ACCEPTANCE.md)。

## Windows 首次安装

在项目根目录打开 `pwsh -NoProfile`。需要 Python **3.12**、uv、Git、Node.js **24.14+** / npm；自动浏览器验收需要系统 Edge。已验证 Python3.12.7 / uv0.12.0 / Node24.14.1 / npm11.11.0 / PostgreSQL18.6；依赖以 [uv.lock](uv.lock) 和 [package-lock.json](frontend/package-lock.json) 为准。

```powershell
uv sync --locked --python 3.12
./scripts/frontend.ps1 install
# 没有PostgreSQL时；首次setup前不要创建.env，脚本生成数据库凭据。
# 中文路径需要未占用的可写ASCII联接路径，按本机情况替换。
./scripts/setup_postgres.ps1 setup -RuntimeAlias D:/after-sales-pg-runtime
```

独立版下载并校验锁定的PostgreSQL18.6，只监听127.0.0.1:55432，不注册系统服务。联接指向项目 `.runtime`，不移动数据；保留联接及 `.runtime/pg-runtime-alias`。已有本项目数据库用 `./scripts/setup_postgres.ps1 start`，不要再次初始化。

已有本地PostgreSQL时，创建普通应用角色及其拥有的 `after_sales_dev` / `after_sales_test` 两个库，复制 [.env.example](.env.example) 为 `.env`，填写loopback连接。角色需能创建schema，不需要superuser。测试仅允许 `after_sales_test`；不要使用真实业务数据。

在 `.env` 添加 `DEEPSEEK_API_KEY`，模型固定 `DEEPSEEK_MODEL=deepseek-flash`（DeepSeek-V4.1-Flash）。不要放入VITE变量、聊天或版本控制。live调用会发送项目模拟业务上下文；没有密钥仍能运行确定性后端和pytest，聊天明确失败，不伪造回复。

```powershell
$env:BUSINESS_CLOCK_MODE = 'fixture'
./scripts/backend.ps1 migrate
./scripts/backend.ps1 seed
$env:PYTHONPATH = Join-Path (Get-Location).Path 'backend'
./.venv/Scripts/python.exe -m alembic check
```

重复seed不覆盖已有业务。演示fixture时钟为 **2026-10-11 10:00 Asia/Shanghai**，仅DEV_MODE可用；session到期与worker租约按真实UTC。默认system时钟会让历史模拟订单超出窗口。

## 启动工作台

四个独立PowerShell终端，同一项目根目录和.env：

```powershell
# 终端1：API；已有本项目服务时不要重复启动
$env:BUSINESS_CLOCK_MODE = 'fixture'
./scripts/backend.ps1 serve
# 终端2：Agent持久化消息任务
$env:BUSINESS_CLOCK_MODE = 'fixture'
./scripts/backend.ps1 agent-worker -Watch
# 终端3：已满足审核和收货条件的模拟退款
$env:BUSINESS_CLOCK_MODE = 'fixture'
./scripts/backend.ps1 worker -Watch
# 终端4：前端
./scripts/frontend.ps1 dev
```

打开[工作台](http://127.0.0.1:5173/)、[健康检查](http://127.0.0.1:8000/api/v1/health)、[API文档](http://127.0.0.1:8000/docs)。仅监听loopback，前端同源代理/api。生产本地预览：`./scripts/frontend.ps1 build` 后 `./scripts/frontend.ps1 preview`（同样5173，先停dev）。

| 身份 | 操作范围 |
|---|---|
| C-A1/C-A2/C-B1 | 自己的订单、咨询、草稿、摘要确认；C-A2拥有O-A108 |
| E-A1 | A店客服，不能审核或收货 |
| E-A2/E-B2 | 各自店铺审核员 |
| E-A3 | A店仓库 |

业务列表在左，详情和时间线在右。默认咨询只读；申请/人工工单需显式选择操作。客户生成后端摘要并确认提交，再切独立审核/仓库身份。退款成功依据后端流水，不依据模型文字。见[三剧本](docs/11_DEMO_RESUME.md)、[接口](docs/04_API_TOOLS.md)、[录屏](docs/19_DEMO_RECORDING.md)。

停止各终端用Ctrl+C，先停worker再 `./scripts/setup_postgres.ps1 stop`。消息和退款任务保留；Agent崩溃后等15秒租约到期重启，恢复原预算内任务。取消聊天不回滚已写入业务。

## 验证与复现

```powershell
# 真实PostgreSQL，每例独立schema，保留开发库
./scripts/backend.ps1 test
./scripts/frontend.ps1 build
./.venv/Scripts/ruff.exe check backend scripts
./scripts/validate_handoff.ps1
# 配置真实模型后；独立测试schema，8105/5174须空闲
$env:BROWSER_ARTIFACT_DIR = Join-Path (Get-Location).Path ('artifacts/local_browser_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
./.venv/Scripts/python.exe scripts/browser_m5.py
Remove-Item Env:BROWSER_ARTIFACT_DIR
# 只读复核本次交付证据，不覆盖历史M4/M5
./.venv/Scripts/python.exe scripts/verify_m6.py
# 校验最终源码包；实际文件名见dist
./.venv/Scripts/python.exe scripts/package_m6.py verify dist/after-sales-agent-0.6.0-local-m6.zip
```

完整交付复现：`scripts/reproduce_m6.py <源码包>` 解压到新目录，干净安装、生产构建，创建全新 `after_sales_m6_UUID` 数据库并迁移/重复导入，执行311项回归及live浏览器录屏。需要项目独立版 `.runtime/admin-password`，仅创建/删除临时库，业务仍用普通角色。端口8106/5175不占用现有8000/5173；只清理自己的库。证据写 `artifacts/m6`，已有报告拒绝覆盖；重复运行先归档旧报告目录。普通安装不需要管理员文件或打包脚本。

```powershell
# 复跑M4评测数据，输出必须是新目录，离线不计live成绩
./.venv/Scripts/python.exe scripts/run_evals.py --baseline all --repeats 1 --output evals/reports/local_offline
./.venv/Scripts/python.exe scripts/run_evals.py --dataset holdout-v2 --live --baseline all --repeats 3 --output evals/reports/local_holdout_v2_live
```

[M4历史验收](docs/16_M4_ACCEPTANCE.md)：当时新独立集Agent36/36、可核查事实217/223（97.3%）、引用有效率100%、P95 9.203秒、硬约束零违规；首批27/33（81.8%）失败保留。数据/冻结哈希/分母/基线/原始失败均在evals。M6保留四个冻结Agent/prompt/model/grounding文件，另修复checkpoint持久化（checkpoint-v2-m6，ADR-020）；原成绩不扩大到新组件。模型非确定性，不保证逐字复现；后续调优需新的人工核验独立集。M6三剧本只是功能复现，不是新泛化成绩。

[M5历史验收](docs/17_M5_ACCEPTANCE.md)：308项回归、两项浏览器检查、5个live run、3笔唯一模拟退款64700分。当前交付使用verify_m6；历史verify_m2/3/4/5绑定当时实现，不用它们覆盖旧证据。旧HTTP smoke会写开发库，不与常驻worker混跑。

[M6本地交付](docs/18_M6_ACCEPTANCE.md)：干净锁文件安装、新物理PostgreSQL数据库迁移/重复seed、311项完整回归、两项生产浏览器测试通过。5个live run完成三剧本，3笔唯一模拟退款64700分，开发库不变；录屏228.2秒。证据在[机器核验](artifacts/m6/verification.json)，源码包在dist（包含每文件SHA256清单，排除密钥/依赖/数据库/视频），录像artifacts/m6/demo.webm单独交付。M6三轮初始问题分别保留，不覆盖旧成绩。

## 架构与限制

[实际架构和源码地图](docs/02_ARCHITECTURE.md)：FastAPI身份/权限 → 确定性领域服务 → PostgreSQL业务/任务/checkpoint；单LangGraph Agent仅十个有限工具。审核、收货、退款、政策修改和任意SQL不是模型工具。检索为同库授权过滤加中文关键词，无向量库。

本地模拟MVP，没有生产认证、真实支付、部署、图片上传/自动鉴定、SSE、多Agent或人工工单关闭流程。仅单件整单退款，提交后无自动变更。界面最近50条消息/100条事件，刷新恢复限同一标签页。结构化事实准确率不等于全部自然语言正确，N12引用支撑不足已有语义复核记录。模型和业务数据都不可信，后端守卫独立执行。

阅读：[PRD](docs/01_PRD.md) → [规则](docs/03_DOMAIN_RULES.md) → [决策](docs/DECISIONS.md) → [计划](docs/07_DEVELOPMENT_PLAN.md) → [状态](PROJECT_STATUS.md)。源码包排除.env、数据库、依赖和原始运行日志；录屏单独交付，历史成绩保留。

## 开源与复用

公开仓库：[Mimicif/ecommerce-after-sales-agent](https://github.com/Mimicif/ecommerce-after-sales-agent)，采用 [MIT 许可证](LICENSE)。

```powershell
git clone https://github.com/Mimicif/ecommerce-after-sales-agent.git
cd ecommerce-after-sales-agent
```

克隆后按上面的首次安装与启动步骤运行。仓库包含源码、锁文件、模拟数据、测试、评测和历史验收证据；模型密钥、数据库、依赖目录、源码压缩包与演示视频仅保留在本地。`dist/` 和 `artifacts/m6/demo.webm` 不随 Git 克隆分发，可在本地按交付脚本生成。真实模型评测需要自己的供应商密钥与调用费用；历史成绩对应报告中记录的版本和数据，不代表本次开源重新运行了评测。
