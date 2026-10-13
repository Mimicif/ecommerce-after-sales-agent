# 企业Agent工程实践调研

调研日期：2026-10-11。依据官方公开资料。公开文档不能证明某家公司的全部内部流程，也不存在一个适用于所有大厂的统一Agent开发SOP。
下列生命周期是综合建议；本项目的阶段、数值门槛和实现方式另由项目文档规定。

## 可以从公开资料确认的实践

### 简单方案和可控自治

Anthropic区分预定义workflow和由模型决定行动路径的agent，并建议从简单组合开始，按需要增加复杂度。
本项目采用固定售后状态机加有限的动态工具选择，先验证单Agent价值。
来源：[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)，2024-12-19。

### 先定义要求，再选择架构

Google Cloud的设计指南从任务复杂度、性能、成本和人介入需求评估开始，再选择单Agent或多Agent模式。
本项目先明确三类业务、退款权限、等待条件和预算，再选择框架。
来源：[Choose a design pattern for your agentic AI system](https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system)，页面标注审阅2026-05-28。

### 工具是产品接口

Anthropic强调工具应匹配Agent任务，名称、schema和说明需要清楚，输出与错误应有用；工具数量多不等于效果好。
本项目只提供少量查单、政策、资格和申请工具，审批与支付权限留在后端。
来源：[Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)，2025-09-11。

### 评测不止看最终一句回复

Anthropic的Agent评测文章讨论多轮轨迹、任务、评分器、环境状态及反复运行等因素。
本项目用数据库终态判定是否提交/退款，以trace定位错误，并保留语义和人工检查。
来源：[Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)，2026-01-09。

### 明确行为和安全边界

Microsoft的Agentic Behavior Engineering把允许、必须和禁止的行为、验证方式及运行边界作为工程对象。
本项目对应客户确认、权限、审批、金额守卫和转人工终点。
来源：[Agentic Behavior Engineering](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/agentic-behavior-engineering)，访问2026-10-11。

### 用观测形成持续改进循环

Microsoft/Azure Databricks资料描述从trace发现问题、收集反馈、整理数据集、写评分器、修复、再评测和监控的循环。
本项目从首个工具执行就记录trace，将失败变体纳入回归集。
来源：[Agent observability and quality](https://learn.microsoft.com/en-us/azure/databricks/mlflow3/genai/agent-observability-and-quality)，访问2026-10-11。

### 恢复不能替代业务幂等

LangChain官方文档源码提醒任务可能重新运行，API和副作用要按可重试、幂等方式设计。
本项目用checkpoint加业务唯一键、退款结果查询和对账，不把框架持久化当作不会重复支付的保证。
来源：[LangGraph Functional API官方文档源码](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/functional-api.mdx)，访问2026-10-11。

## 可借鉴的完整生命周期

| 阶段 | 关键问题 | 可审查产物 |
|---|---|---|
| 业务定义 | 谁用、频次、痛点、成功和成本是什么 | PRD、用户故事、人工基线 |
| 权限与数据 | 可访问什么、可做什么、哪些动作需人决定 | 数据字典、工具合同、身份/权限矩阵 |
| 原型 | 固定流程能否解决，何处需要模型 | 小范围PoC、可追溯执行 |
| 工程化 | 如何恢复、去重、限额、隔离 | 状态机、持久化、幂等、预算与观测 |
| 离线验证 | 任务是否完成、是否越权、成本延迟如何 | 固定评测、对抗/错误场景、失败报告 |
| 试运行 | 先只读或影子运行，有人工兜底吗 | 试点范围、审批链、异常处理与回退 |
| 上线 | 版本可否追溯，异常是否可止损 | 分环境发布、监控、写入开关、对账 |
| 持续优化 | 用户失败反馈如何进回归 | trace→案例→评分→修复→评测循环 |

这是对公开实践的归纳，不是获知了阿里、腾讯或字节的内部审批流程。
采购、合规、隐私、组织分工和模型训练等因公司和业务而变化。

## 个人项目采用什么

必须：需求边界、确定性业务层、工具schema、身份和资源权限、持久化、幂等、trace、固定评测、版本、真实运行说明。
按需：向量检索、重排、多模型路由、SSE、消息队列。
第一版不必：多Agent平台、模型微调、Kubernetes、复杂服务网格。
成熟的表现是知道何处需要复杂度，并用失败数据证明选择。
