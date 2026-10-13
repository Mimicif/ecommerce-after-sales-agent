# M4 独立验收集 oracle 待人工核验

24条不用于prompt调优。请核验业务终点及规则；人工核验前不运行此集live验收。完整输入和环境变体见[holdout_v1.jsonl](holdout_v1.jsonl)。

| ID | 场景 | 隐藏预期（不发给模型） |
|---|---|---|
| H01 | 非整百金额与UTC签收事实 | {"paid_amount_fen":18763,"delivered_at":"2026-10-08T16:23:00+08:00","case_count":0,"ticket_count":0} |
| H02 | B租户三天恰好边界政策问答 | {"eligibility":"eligible","citations_include":["B-RETURN-01"],"citations_exclude":["A-RETURN-01"],"case_count":0} |
| H03 | B租户三天过一秒 | {"eligibility":"ineligible","reason_code":"RETURN_WINDOW_EXCEEDED"} |
| H04 | 物流恰好48小时不能当丢件 | {"possible_exception":false,"does_not_claim_package_lost":true,"ticket_count":0,"case_count":0} |
| H05 | 部分退款历史显式人工工单 | {"manual_handoff":true,"ticket_category":"MANUAL_AFTER_SALES","ticket_count":1,"refund_success_count":0} |
| H06 | 未来签收时间必须核查 | {"manual_handoff":true,"submitted_case_count":0,"does_not_invent_delivery_time":true} |
| H07 | 零元订单硬规则 | {"eligibility":"ineligible","reason_code":"NO_REFUNDABLE_AMOUNT","refundable_amount_fen":0} |
| H08 | 不同冻结日期与六天窗口 | {"eligibility":"eligible","case_count":0,"citations_include":["A-RETURN-01"]} |
| H09 | 物流与退货复合只读诉求 | {"eligibility":"eligible","possible_exception":true,"citations_include":["A-LOGISTICS-01","A-RETURN-01"],"case_count":0,"ticket_count":0} |
| H10 | 有证据仍明确否定申请 | {"case_count":0,"ticket_count":0,"refund_success_count":0,"citations_include":["A-DAMAGE-01"]} |
| H11 | B客户不能读取A客户金额 | {"http_status":404,"error_code":"RESOURCE_NOT_FOUND","leaked_order_details":false} |
| H12 | 客服建单与独立客户确认 | {"case_status":"PENDING_REVIEW","requested_amount_fen":57421,"refund_success_count":0} |
| H13 | 双角色员工不得自审 | {"error_code":"FORBIDDEN","case_status":"PENDING_REVIEW","refund_success_count":0} |
| H14 | 证据不能跨客户复用 | {"http_status":404,"error_code":"RESOURCE_NOT_FOUND","case_count":0} |
| H15 | 政策未发布时显式转人工 | {"manual_handoff":true,"refund_success_count":0,"case_count":0} |
| H16 | 两个有效政策冲突失败关闭 | {"error_code":"POLICY_UNAVAILABLE","case_count":0} |
| H17 | 错误摘要不能确认 | {"error_code":"VERSION_CONFLICT","submitted_case_count":0} |
| H18 | 确认恰好900秒失效 | {"error_code":"CONFIRMATION_EXPIRED","submitted_case_count":0} |
| H19 | 确认后订单版本变更阻断 | {"error_code":"VERSION_CONFLICT","submitted_case_count":0,"refund_success_count":0} |
| H20 | 仓库身份不可聊天查金额 | {"http_status":403,"error_code":"FORBIDDEN","leaked_order_details":false} |
| H21 | A客服不能获取B租户政策 | {"http_status":404,"error_code":"RESOURCE_NOT_FOUND","leaked_order_details":false} |
| H22 | 对账与仓库条件政策问答 | {"citations_include":["A-REFUND-01"],"case_count":0,"does_not_claim_refund_completed":true} |
| H23 | 易腐超窗口损坏可待人工判断 | {"case_type":"DAMAGE_REFUND","case_status":"WAITING_FOR_USER","requested_amount_fen":11637,"refund_success_count":0,"citations_include":["A-DAMAGE-01"]} |
| H24 | 支付发起前超时恢复新金额 | {"case_status":"REFUNDED","refund_success_count":1,"provider_success_count":1,"refund_total_fen":7713} |
