# 架构 v1.1（M6，实际实现）

## 默认技术选择

| 层 | 选择 | 理由与边界 |
|---|---|---|
| 后端 | Python、FastAPI、Pydantic | API、schema和模型调用集中在一个服务 |
| 数据 | PostgreSQL、SQLAlchemy、Alembic | 事务、行锁、唯一约束、迁移、检索 |
| 编排 | LangGraph 1.2.14（M3已接入） | PostgreSQL checkpoint及等待用户；业务幂等仍由后端实现 |
| 模型 | DeepSeek-V4.1-Flash / HTTPX | model_id=deepseek-flash，单供应商工具调用适配层 |
| 检索 | PostgreSQL元数据过滤 + 中文keyword_v1检索 | 同库授权过滤与条款排名；无向量优化需求证据 |
| 前端 | React、TypeScript | 客户聊天、审核台、执行轨迹 |
| 运行 | 本地API + Agent worker + 模拟退款worker | 使用数据库持久化任务；不先引入Redis/Celery |
| 测试 | pytest、HTTP集成测试、前端关键流程测试 | 涉及并发和事务必须使用PostgreSQL |

当前实际版本以uv.lock与frontend/package-lock.json为准；前端轮询同源API。

## 数据流

~~~mermaid
flowchart TD
 U[客户或客服] --> API[身份验证后的API]
 API --> DB[(PostgreSQL)]
 API --> Q[持久化run任务]
 Q --> W[单worker与LangGraph]
 W --> M[模型适配器]
 W --> T[有schema和权限的工具层]
 T --> D[确定性领域服务]
 T --> R[政策检索]
 D --> DB
 R --> DB
 A[审核员与仓库] --> API
 API --> D
 D --> J[持久化模拟退款任务]
 J --> RW[独立模拟退款worker]
 RW --> P[模拟支付：独立事务与稳定幂等键]
 P --> DB
 W --> E[脱敏事件与轨迹]
 E --> DB
 API --> UI[轮询执行事件与业务状态]
~~~

## 模块边界

- api：鉴权、参数校验、HTTP错误、资源权限；不把请求内的tenant字段作为可信身份。
- domain：资格、金额、确认、审核、退货、退款状态；不调用LLM。
- repositories：事务、数据库约束、版本比较、任务锁。
- tools：LLM可见的有限工具，复用domain逻辑。
- agent：路由、澄清、工具选择、上下文和执行预算；不能直写业务表。
- retrieval：授权过滤、政策版本选择、中文关键词召回、引用。
- workers：持久化run、退款job、重试与结果对账。
- providers：LLM及模拟支付适配器，明确超时与错误。
- evals：规格加载、环境复位、驱动多轮对话、代码判定与报告。

## 持久化执行

POST消息先落库再创建run。一个conversation同时只允许一个活动run；重复消息用client_message_id去重。
worker在短事务内获取任务并记录lease，事务外调用模型或远端工具。不得持有数据库锁等待LLM。
lease过期后恢复；节点重放可能重复执行，所有业务写工具仍需要幂等保护。
状态与checkpoint不是同一事实源：业务表是订单和资金事实；checkpoint记录编排进度。
恢复前读取业务现状并核对，不根据旧聊天内容宣称已退款。
不同conversation对同一订单的并发由订单行锁与活动case约束处理。

## 失败与资源边界

单run默认45秒、最多8次模型调用、12次工具调用；预算属于可调整项目设定。
超过预算停止为FAILED并保留checkpoint/业务状态供审计，不能通过重启扩大原预算；用户可读状态或另发消息。进程崩溃而预算未耗尽时恢复原run。
查询请求可有限重试；有副作用请求先查状态，重试必须沿用稳定幂等键。
模型不可用时仍提供确定性查单/人工表单；不伪造Agent回复。
外部写入前的intent与本地结果之间可能崩溃，因此使用持久化job + 幂等外部操作 + 对账，而不承诺分布式exactly-once。

## 实际源码地图

| 文件 | 职责 |
|---|---|
| backend/app/main.py、workspace.py | HTTP、发现列表与详情、后端身份和授权 |
| backend/app/domain.py、reads.py、writes.py | 确定性规则、只读查询、状态与版本校验 |
| backend/app/models.py、db.py、backend/migrations | PostgreSQL模型、事务与迁移 |
| backend/app/agent.py、agent_store.py、agent_checkpoint.py | LangGraph、持久化run/租约/checkpoint |
| backend/app/agent_model.py、agent_tools.py、tools.py | DeepSeek适配与十个有限模型工具 |
| backend/app/retrieval.py、policy.py、grounding.py | 授权政策检索、摘要完整性、结构化声明核查 |
| backend/app/refunds.py、cli.py | 独立模拟支付结果、退款对账、两个worker命令 |
| backend/app/evaluation.py、eval_driver.py、eval_score.py | 数据集加载、执行、代码判定与报告 |
| frontend/src、frontend/e2e | React流程界面与真实浏览器验收 |
| scripts/package_m6.py、reproduce_m6.py | 源码清单、干净安装与全新数据库交付检查 |

采用单体服务与具体模块，没有为概念边界创建空目录或微服务。Agent与退款worker分别启动，不持有数据库锁等待模型或模拟供应商结果。模拟支付与业务账本使用不同事务，靠稳定幂等键及查询恢复保障唯一记账。
