"""B0 fixed routing/form baseline. Input only, with the same authorized business APIs."""

import re

from app.errors import BusinessError
from app.grounding import observed_facts


class FormBaseline:
    def __init__(self, driver, fault):
        self.driver, self.fault = driver, fault
        self.observations, self.citations, self.retrieved, self.responses = [], [], [], []

    def read(self, name, order, body=None):
        paths = {
            "get_order": f"/orders/{order}",
            "get_logistics": f"/orders/{order}/logistics",
            "check_eligibility": f"/orders/{order}/eligibility",
            "get_case": f"/cases/{order}",
        }
        self.fault.before(name)
        data = self.driver.ok(paths[name], body, method="POST" if body else "GET")
        self.observations.extend(observed_facts(name, {"order_id": order}, data))
        return data

    def policy(self, order, intent, query):
        from urllib.parse import urlencode

        data = self.driver.get(
            f"/orders/{order}/policy?" + urlencode({"intent": intent, "query": query})
        )
        self.observations.extend(observed_facts("search_policy", {}, data))
        self.retrieved.extend(c["chunk_id"] for c in data["clauses"])
        self.citations.extend(c["citation"] for c in data["clauses"])

    def turn(self, request):
        text, action = request["content"], request.get("action", "CONSULT")
        ids = list(dict.fromkeys(re.findall(r"O-[A-Z]\d{3}", text)))
        if not ids:
            self.driver.get("/orders")
            self.responses.append({"answer": "请提供或选择订单号。", "needs_input": True})
            return
        answer, waiting = [], False
        for order_id in ids:
            try:
                order = self.read("get_order", order_id)
                if "售后进展" in text and order["cases"]:
                    case = self.read("get_case", order["cases"][0]["id"])
                    answer.append(
                        "审核拒绝，需要人工补充材料。"
                        if case["status"] == "REJECTED"
                        else case["status"]
                    )
                    continue
                logistics = any(
                    word in text for word in ("物流", "更新", "丢", "到哪", "包裹", "轨迹")
                )
                damage = any(word in text for word in ("坏", "裂", "损坏", "破损"))
                returns = damage or any(word in text for word in ("退", "申请", "不喜欢", "不想要"))
                intent = (
                    "LOGISTICS" if logistics else ("DAMAGE_REFUND" if damage else "RETURN_REFUND")
                )
                if logistics or returns:
                    self.policy(order_id, intent, text)
                if logistics:
                    data = self.read("get_logistics", order_id)
                    answer.append(
                        "可能物流异常，需人工核查，不能认定丢件。"
                        if data["possible_exception"]
                        else "物流运输中。"
                    )
                eligibility = (
                    self.read("check_eligibility", order_id, {"case_type": intent})
                    if returns and not logistics
                    else None
                )
                if eligibility:
                    answer.append(
                        "可以申请，需审核。"
                        if eligibility["eligibility"] == "eligible"
                        else "需要按资格结果核查或人工处理。"
                    )
                if action == "CREATE_TICKET" and request.get("target_order_id") == order_id:
                    category = "LOGISTICS" if logistics else "MANUAL_AFTER_SALES"
                    self.driver.ok(
                        "/tickets",
                        {"order_id": order_id, "category": category, "summary": text},
                    )
                    answer.append("已创建人工核查工单。")
                elif action == "APPLY_AFTER_SALES" and request.get("target_order_id") == order_id:
                    evidence = re.findall(r"EVIDENCE-[A-Z]\d+", text)
                    if damage and not evidence:
                        answer.append("请提供损坏描述和证据引用。")
                        waiting = True
                    elif (
                        eligibility
                        and eligibility["eligibility"] == "eligible"
                        or damage
                        and evidence
                    ):
                        case = self.driver.draft(
                            {
                                "order_id": order_id,
                                "case_type": intent,
                                "reason": text,
                                "evidence_refs": evidence,
                            }
                        )
                        self.driver.summary(case)
                        answer.append("草稿待客户独立确认后提交审核。")
                        waiting = True
                elif damage and not re.findall(r"EVIDENCE-[A-Z]\d+", text):
                    answer.append("请提供损坏描述和证据引用。")
                    waiting = True
                answer.append(
                    f"{order_id}支付{order['paid_amount_fen']}分，"
                    f"签收时间{order['delivered_at'] or '待核实'}。"
                )
            except BusinessError as error:
                answer.append(f"查询失败（{error.code}），需要人工核查，不能认定丢件。")
                # Explicit ticket authorization is usable even when a read provider failed.
                if action == "CREATE_TICKET" and request.get("target_order_id") == order_id:
                    self.driver.ok(
                        "/tickets",
                        {
                            "order_id": order_id,
                            "category": "LOGISTICS" if "物流" in text else "MANUAL_AFTER_SALES",
                            "summary": text,
                        },
                    )
                    answer.append("已创建人工核查工单。")
        self.responses.append({"answer": "".join(answer), "needs_input": waiting})
