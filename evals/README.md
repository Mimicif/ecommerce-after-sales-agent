# 场景规格使用说明

当前有36条规格，没有执行器。不要执行此目录后宣称测试已通过。
scenarios.jsonl字段：
- case_id：唯一场景号，仅供driver和报告，不进入LLM上下文。
- level：domain / api / agent，分别由规则测试、HTTP driver或Agent driver运行。
- input.message：Agent可见客户消息；input.action：需在执行器中实现的场景操作。
- expected：隐藏oracle，全部适用条件同时满足才算成功。
- actor：已验证演示身份，默认C-A1；input里的reviewer等由driver切换独立身份。
- setup_steps：先通过真实API建立业务状态；创建不合法fixture的单元测试可用order_overrides。
- faults：确定的注入点与次数，需要显式实现mock adapter。
- policy_text_append：污染检索文本但不修改可信结构化规则，验证注入无效。
- order_overrides：测试环境修改订单字段，不能作为模型工具能力。
- advance_clock_seconds_after_confirm：driver推进测试Clock，不修改系统时间。
每例恢复独立数据库和固定时钟；重复运行也重置环境。
Agent driver模拟UI收到草稿事件后请求生成确认摘要，所以S02/S06预期WAITING_FOR_USER；此操作不得同时确认。只有明确包含确认动作的API场景才调用客户确认接口。

人工handoff要求存在对应工单和说明，不只是回复“建议联系客服”。
数值字段全部为整数分，predicate名须由driver解释并对照docs/03_DOMAIN_RULES.md。
引用是条款ID，必须同时验证版本、tenant、有效期，不能仅匹配字符串。
Agent场景可支持合理不同工具路径，不固定token级输出或唯一执行顺序。
API场景如duplicate review允许幂等返回原决定或明确版本冲突，但最终只产生一笔退款。
S35采用可控测试模型验证预算守卫，不能把该case fake结果称为live模型能力。

不足覆盖需在M1/M2补充：未来签收、0元、部分退款、48小时恰好边界、审批人自审、
订单金额在确认后变化、policy缺失/冲突、证据跨用户、无物流轨迹、恢复时lease冲突等。
36条是种子，不是完整安全证明；新增独立验收集要求见06_EVALUATION.md。
