# M3 验收条件（开发前定义）

范围：DeepSeek-V4.1-Flash（官方API model_id=deepseek-flash）、LangGraph单Agent、十个有限业务工具、PostgreSQL持久化会话/run/checkpoint/事件、独立worker与轮询。没有前端或M4全面评测。

完成条件：
- 真实供应商参数核验并锁定依赖；密钥仅本地配置，非thinking，不保存隐藏推理，不发LangSmith云追踪。
- 多轮查单/澄清→草稿→等待客户→真实客户确认→提交；物流异常与人工工单均有可审计事件。
- 默认CONSULT只读；客户请求显式声明APPLY_AFTER_SALES/CREATE_TICKET/SUBMIT_CONFIRMED后才开放相应写工具。没有确认/审核/仓库/退款/SQL模型工具。
- client_message_id去重、单会话单活动run、租约与令牌、checkpoint重启恢复、写入后checkpoint前崩溃不重复建单；预算45秒/8模型调用/12工具调用（包含重试）。
- 跨客户/租户/会话、角色撤销、伪造参数/权限、纯咨询误建单、虚构资金成功、无确认提交、工具失败最多一次修正均有真实PostgreSQL或合同测试。
- 实际HTTP/模型验收与离线fixture测试分别记录；没有真实调用证据不能把M3标为全部完成。

实现选择和差异见ADR-016；通过后再追加实际结果。

## 实际交付（2026-10-12，完成）

先定义上述条件后编码；用户选择DeepSeek并在本项目.env配置密钥。官方[模型及价格](https://api-docs.deepseek.com/quick_start/pricing/)确认deepseek-flash对应DeepSeek-V4.1-Flash，支持非thinking工具调用。直接HTTPX0.28.1接入Chat Completions；langgraph1.2.14、langgraph-checkpoint4.2.0、langchain-core1.6.9和全部间接依赖锁定于uv.lock。没有使用OpenAI SDK或LangSmith云追踪。

迁移0004_m3增加7张表：conversations/chat_messages/agent_runs/run_events/agent_invocations/graph_checkpoints/graph_writes。显式Alembic迁移、真实PostgreSQL18.6，单根图JSON-only checkpoint；单会话单活动run唯一索引、client_message_id及seq唯一约束、预算/租约约束。
写工具必须匹配action和客户选择的target_order_id；缺目标需补问，其他订单失败。既有M2权限、金额、政策、证据、版本、客户确认和事务继续生效；十工具无确认/审核/仓库/退款/SQL。预算45秒/8模型/12工具，租约15秒，单次请求10秒，稳定业务键按run+逻辑工具步骤生成；模型结果缓存防止checkpoint前中断重付模型费用。

### 验证结果

- 245 passed，0 failed/errors/skipped，258.56秒；M0 21、M1接口/工具63、M1领域25、M2 97、M3新增39。无弃用警告。离线ScriptedModel明确标FAKE，仅验证合同/真实图/真实PostgreSQL，不称模型成绩。
- M3覆盖模型参数错误、越权及跨用户/租户/会话、角色撤销、纯咨询阻断写入、无确认提交、目标订单绑定、状态/来源声明、错误最多一次修正、8/12调用与deadline、并发消息/两worker、旧租约、取消不删除业务资源、文本脱敏。
- 三个崩溃位置均恢复：写效果后checkpoint前（一个草稿、一次工具效果）；模型响应落库后checkpoint前（不再次调用模型）；图完成后run完成事务前（一个assistant消息）。均使用真实PG/checkpoint及新的worker对象。
- 真实HTTP和独立CLI worker共9个DeepSeek run：8个成功（4 COMPLETED、4 WAITING_FOR_USER）及1个保留的初次最终JSON失败。首次失败时提交实际已成功，严格输出合同返回FAILED，没有伪装成功或新建申请；修正历史记忆和三字段约束后读现有状态恢复。C-A2/O-A108又完成新的干净草稿→客户独立确认→提交流程。
- live包括多订单澄清、普通退货草稿/确认后提交、物流异常/OPEN工单、损坏证据补问、B租户政策查询及隔离；没有真实支付。O-A102申请39900分、O-A108申请9900分，均PENDING_REVIEW，没有退款job或流水。M2原两笔模拟退款仍合计23800分。
- 运行20次模型调用、21次工具调用；真实run用量输入57212/output2529，共59741tokens。另一次模型能力探针输入1729/output48。含探针合计61518tokens；官方非高峰/高峰估算USD0.00549519–0.01099038，不是账单。核验日期2026-10-12：每百万tokens缓存输入0.003–0.006、未命中输入0.15–0.30、输出0.60–1.20美元。
- M0/M1/M2 HTTP回归、Alembic check无差异、重复seed保留数据、实际schema合同一致、Ruff/format、文档链接检查与只读资金对账均通过。M1旧冒烟因O-A102已有活动申请改为验证ACTIVE_CASE_EXISTS，保留真实业务数据。

### 运行及证据

~~~powershell
$env:BUSINESS_CLOCK_MODE = 'fixture'
./scripts/backend.ps1 migrate
./scripts/backend.ps1 seed
./scripts/backend.ps1 serve
# 另一个终端，消息入队后执行；处理当前队列后退出：
$env:BUSINESS_CLOCK_MODE = 'fixture'
./scripts/backend.ps1 agent-worker
# 离线回归及真实模型HTTP演示：
./.venv/Scripts/python.exe -m pytest --junitxml=artifacts/m3/pytest.xml
./.venv/Scripts/python.exe scripts/smoke_m3.py --fresh-customer --output artifacts/m3/live_repeat.json
./.venv/Scripts/python.exe scripts/export_contracts.py
./.venv/Scripts/python.exe scripts/verify_m3.py
~~~

[对账报告](../artifacts/m3/verification.json)、[离线测试](../artifacts/m3/pytest.xml)、[真实模型及干净流程](../artifacts/m3/live_clean.json)、[初次失败](../artifacts/m3/live_initial_failure.json)、[修复后六轮](../artifacts/m3/live_http.json)。M0–M2历史证据与合同保留，不覆写成M3成绩。

限制：M3少量live验收不代表M4的36场景及24独立样本完整评测；中文相关度检索仍未实现。自然语言说明的数字/语义质量仍需M4评测，后端事实卡和规则引擎控制业务。checkpointer只支持本图空namespace；worker为本地按需批次进程，无常驻调度。客户session/冻结Clock/支付都是本地演示；没有前端、线上部署或真实退款。
