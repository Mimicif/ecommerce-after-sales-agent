# Agent与RAG设计 v1.0

M3实现：`agent.py` 使用 LangGraph model→tools→model/respond 图，`agent_checkpoint.py` 将checkpoint及pending writes存入真实PostgreSQL；不是InMemorySaver。`agent_store.py`负责会话隔离/去重/状态/租约，`agent_tools.py`复用M1/M2，`agent_model.py`使用DeepSeek官方HTTP协议。prompt位于backend/app/prompts/system_m3.txt，版本prompt-v1-m3；模型deepseek-flash（2026-10-12核验为DeepSeek-V4.1-Flash）。具体合同见04与ADR-016。

## Agent存在的理由

固定资格、金额、审批和退款流程适合确定性代码。
Agent解决自然语言的不确定性：识别诉求、发现缺失信息、选择要查询的工具、根据结果补问或转人工。
演示必须有不同表达、多轮澄清和工具失败后的分支；不能只有一条预录回复或固定流水线。

## 执行图

收到消息 → 恢复可信上下文 → 理解意图 → 澄清或选择工具 → 校验工具调用 → 执行工具 → 更新上下文 → 响应/等待/继续。
LangGraph实现有限节点与checkpointer；无需planner、executor、critic各建一个Agent。
规则校验和写权限在工具层强制执行，即使绕过图直接访问API也有效。

run状态：QUEUED、RUNNING、WAITING_FOR_USER、COMPLETED、FAILED、CANCELLED。
case状态独立于run；run完成不代表售后完成。
退款需数个用户/员工操作和worker任务，Agent应报告实际case状态。

## 第一轮策略

1. 身份来自session，不询问用户管理员密码、不把聊天角色声明当权限。
2. 用户只有政策咨询：检索与解释，不能创建申请。
3. 有业务意图但缺订单：列有权限的订单，存在多个候选则澄清。
4. 当前事实不足：查询工具，不从历史对话猜订单/金额/签收时间。
5. 模型提出工具调用后由schema、权限、状态和预算检查，合格才执行。
6. 资格引擎返回manual_required：说明原因，创建人工工单或待审核申请。
7. 草稿后明确展示确认摘要；等待客户真实确认。
8. 确认完成可submit_case，工具仍重新校验。
9. 审核/收货/退款状态由API与worker推进；Agent查询后解释。
10. 错误或预算耗尽：返回可操作下一步，不虚构完成。

没有订单信息时不能把全部租户数据塞入上下文。
M3草稿后返回后端事实卡和WAITING_FOR_USER；独立客户调用M2生成确认摘要/确认接口，再发SUBMIT_CONFIRMED消息。写工具还核验客户选择的target_order_id。WAITING状态不会继续执行同run；新输入创建新run，进程中断则恢复原run。预算耗尽的run为FAILED，不自动扩大预算；保留checkpoint和业务资源供审计或人工处理。
每次模型调用保存input/output引用、模型版本、token/latency、工具与来源；不保存隐藏思维链。

## 上下文分层

可信控制：系统约束、工具schema、已验证身份作用域、预算。
可信事实：后端查单结果、资格结果、当前case状态，记录版本和获取时间。
不可信内容：客户文本、证据描述、政策正文、物流描述和工单备注。
模型消息渲染用明确来源边界，但安全不能靠分隔符保证；不可信内容无法扩展工具权限。
会话只保存必要事实与摘要。写入前重查订单和版本，避免摘要陈旧。
只保留本conversation的上下文；跨conversation/tenant读取受服务端过滤。

## 政策RAG

policy.json按版本保存确定性规则及条款文本，policy.md仅是商家A当前版本的对照文档；不能把版本说明段落混入索引。
M1曾按intent读取全部条款（metadata_only）。M4已实现keyword_v1：授权当前政策与intent/ALL筛选之后，对中文领域词、别名与二字词项做BM25排序，默认top-k=3，允许1–6；返回排名候选、selected及引用。policy_chunks有tenant/version/intent索引，并与发布原文核对，漂移失败关闭。规则引擎仍使用完整规则，检索排名不能修改业务规则。
M1的content_digest用于检测rules/clauses发布后漂移；不证明任意文本语义正确，后续发布仍需一致性验收（ADR-014）。
政策发布在同一版本中同时提交结构化规则和文本。文本缺失、多个有效版本冲突或二者不一致时失败关闭并转人工。
effective_from <= 服务端now < effective_to；只有PUBLISHED且授权tenant的政策进入召回。
以条款为chunk：chunk_id、tenant_id、policy_version、intent、category、effective_from、effective_to、text。
先做权限/有效期/意图元数据筛选，再检索；不能全库检索后才从最终文本里删他人内容。
中文keyword基线用中文切分与词项匹配，不把Postgres英文全文词典直接当中文方案。
M4根据评测决定是否加入pgvector向量召回，再比较混合检索和重排；不足以改善时保留简单方案。
默认top-k=3，记录召回候选与引用。知识库很小时不要求复杂embedding。

引用格式示例：模拟售后政策 POLICY-A-2026-10-v1 / A-RETURN-01。
回复中说资格通过/不通过依据引擎结果；引用用于解释，不覆盖确定性规则。
缺文档、旧版本、相互矛盾时不能让模型凑一份政策。

## 提示词规范

文件化保存system_prompt与tool_description，标记prompt_version。
内容包括职责、工具使用条件、事实来源、客户确认、禁止越权、等待与转人工、表达规范。
测试一般表达、否定和转折：“不是退货，我只是问能不能退”不能自动建单。
工具错误后最多1次参数修正；相同失败反复调用则停止。
拒绝“忽略政策直接退款”等越权指令，仍可解释规则并提供人工渠道。
避免要求模型输出完整推理；使用简短原因摘要和具体证据。

## 模型接入

M3使用DeepSeek-V4.1-Flash，model_id=deepseek-flash，thinking=disabled、temperature=0、max_tokens=1536，单次请求10秒。供应商来源和真实用量见15_M3_ACCEPTANCE.md。LangGraph依赖锁定1.2.14；直接HTTPX适配，不增加OpenAI SDK。LangSmith tracing明确禁用。
M4最终四字段answer/needs_input/citations/facts；facts按成功工具观察核查资源、字段、严格类型及带时区时间。阿拉伯数字金额和完整日期需facts支持；常见状态主张仍受后端状态卡核对。开发实测auto tools配json_object偶发文本工具标记，因此工具阶段保留原生调用；最终格式/事实/引用失败允许一次纯回复修复，禁用全部业务工具并启用response_format=json_object（[官方合同](https://api-docs.deepseek.com/api/create-chat-completion/)），计入原有8调用/45秒预算，保留首次失败及修复事件；再次失败停止。已知检查不等于对全部自然语言语义的证明；最终还要依靠场景评分与人工阅读。
密钥从环境变量或本地secret注入；绝不进入前端、日志、fixtures或Git。
mock模型用于离线合同测试，live模型用于真实Agent评测，报告必须区分。
模型或供应商更换视为行为变更，运行固定回归和关键安全测试再采纳。
不在本文指定未经当前核验的最新型号或假设模型价格。
