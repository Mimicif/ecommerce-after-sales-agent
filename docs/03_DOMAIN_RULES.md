# 领域模型与规则 v1.0

所有政策是演示规则，不是中国消费者权益的法律结论。真实业务需由业务方另行确认规则和适用性。

## 身份与模型

tenant、customer、employee、order、logistics_event、policy_version、conversation、message、agent_run、run_event、after_sales_case、confirmation、review_decision、refund_job、refund_transaction、support_ticket、audit_event。

最小字段：
- order：id、tenant_id、customer_id、product_category、status、paid_amount_fen、refunded_amount_fen、delivered_at、version。
- case：id、tenant_id、order_id、type、status、reason、evidence_refs、requested_amount_fen、policy_version、version、created_by。
- confirmation：id、case_id、case_version、payload_digest、expires_at、confirmed_by、confirmed_at、consumed_at。
- review：case_id、case_version、reviewer_id、decision、return_required、reason、created_at。
- refund_job：id、case_id、operation_key、status、attempts、next_attempt_at、lease_until。
- refund_transaction：provider_operation_id、operation_key、amount_fen、status、provider_reference。
- audit：actor、action、resource、result、timestamp、trace_id、脱敏摘要。
身份由服务端已验证session注入；模型不能设置tenant_id、审核人、支付状态或当前时间。

## 金额与时间

金额单位为CNY整数分，非负；避免浮点。剩余可退款=实付-已成功退款，不包含失败流水。
仅支持一次整单剩余金额退款；已有部分退款的历史订单转人工，不新增部分退款功能。
提交、审批和执行前重新校验剩余金额；并发操作锁订单并检查版本。
保存UTC带时区时间；展示Asia/Shanghai；测试时间由fixtures注入的Clock控制。
不能由用户说今天是某一天改变规则使用的服务端时钟。

M1默认真实UTC业务时钟；DEV_MODE可通过可信BUSINESS_CLOCK_MODE=fixture读取冻结seed时钟，测试可注入FixedClock。客户端参数不可改时钟，session有效期仍使用真实UTC。

## 模拟资格

常规RETURN_REFUND：
- 状态必须DELIVERED，签收时间不能缺失或在未来。
- category必须STANDARD；CUSTOM和PERISHABLE不自动判断常规退货，转人工。
- 0 <= now-delivered_at <= 7*24*60*60秒，包括恰好7天边界。
- 未全部退款，且无同订单活动case。
- 资格通过只允许提交申请；不自动批准退款。
- 客户声明退货原因即可创建申请；是否拆封等复杂判定首版转人工。

M1实现只读前检，返回assessment_scope=READ_ONLY_PRECHECK；M2已建立case表，增加活动申请提示。创建/提交/审批/执行均在真实事务中重校验，前检不是资金授权。
零元订单返回NO_REFUNDABLE_AMOUNT；已全额退款ALREADY_REFUNDED；部分退款历史PARTIAL_REFUND_HISTORY转人工；缺失/未来签收时间转人工。返回余额非批准退款金额。

DAMAGE_REFUND：
- 已签收订单；补问损坏描述及至少一个模拟evidence_ref。
- 有证据也不能自动认定真伪；全部人工审核。
- 超7天、特殊品类、policy缺失或冲突可转人工工单，不简单依据常规退货窗口拒绝损坏诉求。
- 未签收时描述损坏等矛盾信息先澄清并转人工，不提交自动退款。

LOGISTICS：
- IN_TRANSIT且最近轨迹距离now >48小时判为可能异常，创建物流工单；=48小时尚不触发自动异常标记。
- 已标记EXCEPTION的轨迹直接进入人工物流工单。
- 无轨迹或接口故障不能当作丢件，明确无法确认并转人工。
- 不从物流异常直接推导退款资格。

M1以最新轨迹（同时间按ID）判断；无轨迹或未来轨迹possible_exception=null，manual_required=true。读取失败返回明确错误，不返回伪空轨迹。M1仅给异常信号，不创建工单或判断丢件。

## 状态机

~~~mermaid
stateDiagram-v2
 [*] --> DRAFT
 DRAFT --> WAITING_FOR_USER: 生成确认摘要
 WAITING_FOR_USER --> PENDING_REVIEW: 有效客户确认且提交成功
 WAITING_FOR_USER --> CANCELLED: 客户取消
 PENDING_REVIEW --> AWAITING_RETURN: 审核批准且须退回
 PENDING_REVIEW --> READY_TO_REFUND: 损坏审核批准且明确无需退回
 PENDING_REVIEW --> REJECTED: 审核拒绝
 AWAITING_RETURN --> READY_TO_REFUND: 仓库确认收货
 READY_TO_REFUND --> REFUND_PENDING: worker创建稳定操作
 REFUND_PENDING --> REFUNDED: 对账确认模拟支付成功
 REFUND_PENDING --> MANUAL_INTERVENTION: 持续失败需人工
 MANUAL_INTERVENTION --> REFUND_PENDING: 授权恢复同一操作
 REFUNDED --> [*]
 REJECTED --> [*]
 CANCELLED --> [*]
~~~

常规退货审批只能设置return_required=true。
模型无上述审核、收货、资金执行权限。
已提交的申请不允许聊天直接改金额/订单/类型；取消或变更由人工处理并保留记录。
draft可编辑，但version增加并使旧确认失效。
M2编辑仅原因/证据引用；订单/类型不能替换。WAITING编辑回到DRAFT，须生成新摘要。客户可取消DRAFT/WAITING；提交后的取消/变更仍交人工处理。
退款处理中不能简单取消或建立另一个case，需要对账后由人工判断。

## 客户确认

UI摘要必须包含case、订单、类型、金额、政策版本、须人工审批的说明。
后端生成confirmation并绑定摘要digest及case_version，有效期15分钟。
客户通过已认证确认接口点击确认；单纯LLM声称客户同意不是确认。
now >= expires_at 时确认失效。草稿创建后由客户UI或测试driver请求生成确认摘要，推进WAITING_FOR_USER；生成摘要本身不代表客户已确认。客服创建草稿后仍需真实客户进入此步骤。
纯聊天演示要把客户输入转为同样的确定性确认操作，不允许模型替客户调用确认接口。
确认不可换订单、复用到新版本或由support冒充客户。
过期后重新计算资格与金额并重新展示摘要。提交在事务内消费确认且创建PENDING_REVIEW，失败则回滚。
幂等重复提交先返回已提交原资源；不得因确认已消费而生成第二个case。
version绑定使刚确认后业务变化仍会拒绝过时提交。
提交时同时重新核对order.version、剩余金额和当前有效policy版本；摘要若已过时返回冲突并重新展示。审批通过后保留规则快照，后续支付对照批准金额与实际余额，不能由模型任意改成新政策金额。

## 幂等与权限

- 客户只访问自己订单；客服仅访问本租户授权订单。
- reviewer审核本租户申请；仓库角色仅确认本租户退货收货；worker仅执行已授权job。
- reviewer不能批准自己以员工身份提交的case。
- 对同订单的非终结case建立活动唯一约束；资金不确定的MANUAL_INTERVENTION仍算活动。
- 幂等键按actor、tenant、操作类型和客户端请求键定位，保存请求摘要；同键不同内容返回IDEMPOTENCY_CONFLICT。
- 稳定退款operation_key由后端case产生，不由LLM或每次重试生成。
- 对所有工具和REST接口复用权限校验，不能只在聊天入口鉴权。
- 对他人订单返回RESOURCE_NOT_FOUND，避免泄露是否存在。

## 模拟支付事务边界

1. 审核/仓库事务写READY_TO_REFUND并写入持久化job，数据库唯一约束case_id保证一项退款操作。
2. worker再次检查订单、case版本、金额和授权，在短事务中记录REFUND_PENDING。
3. 调用模拟支付服务，operation_key保持不变。
4. 支付成功但本地写入前崩溃：恢复查询operation_key，取得原成功结果，再在事务中追加唯一流水并更新order与case。
5. 超时未知：不标记成功，不换key；先查provider状态，再有限重试或转人工。
6. 两worker并发或重复回调：唯一流水与订单锁保证累计金额只增加一次。
7. 确认资金状态未知时，Agent回复处理中；只有已对账REFUNDED才能回复模拟退款成功。

M2实际实现：30秒job租约、5秒重试间隔、最多3次失败转人工；旧租约令牌不能回写。业务锁顺序订单→case→job，领取任务独立SKIP LOCKED短事务，支付调用在事务外；退款流水唯一operation_key/case/provider_operation_id，成功流水与订单金额更新同事务。
模拟支付结果保存在simulated_provider_operations的独立事务，用于复现外部已成功/本地未记账；不是生产供应商或真实退款。worker租约与session使用真实UTC，客户确认按可信业务Clock；fixture是明确冻结的开发演示时间。
