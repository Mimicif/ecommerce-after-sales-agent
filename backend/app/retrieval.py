"""Small Chinese lexical baseline, applied only to authorized current policy chunks."""

import math
import re
from collections import Counter

from sqlalchemy import delete, select

from app.models import Policy, PolicyChunk
from app.policy import unavailable

RETRIEVAL_VERSION = "keyword-v1-m4"
TERMS = (
    "退货",
    "退款",
    "签收",
    "窗口",
    "定制",
    "易腐",
    "部分退款",
    "损坏",
    "证据",
    "描述",
    "人工",
    "审核",
    "确认",
    "摘要",
    "有效期",
    "仓库",
    "收货",
    "物流",
    "轨迹",
    "异常",
    "查询失败",
    "对账",
    "七天",
    "7天",
    "48小时",
    "15分钟",
)
ALIASES = {
    "不喜欢": "退货",
    "不合适": "退货",
    "尺寸": "退货",
    "裂了": "损坏",
    "坏了": "损坏",
    "照片": "证据",
    "图片": "证据",
    "包裹": "物流",
    "没更新": "轨迹 异常",
    "停滞": "轨迹 异常",
    "钱到账": "退款 对账",
    "手工": "人工",
    "七天": "7天",
    "七日": "7天",
}


def tokens(text):
    text = text.lower()
    for source, target in ALIASES.items():
        if source in text:
            text += " " + target
    result = [word for word in TERMS if word in text]
    result += re.findall(r"[a-z0-9]+", text)
    for part in re.findall(r"[\u4e00-\u9fff]+", text):
        result.extend(part[index : index + 2] for index in range(len(part) - 1))
    return Counter(result)


def rank(clauses, query, intent, top_k):
    # BM25 over at most six authorized documents, with deterministic intent tie-breaking.
    documents = [tokens(clause.text) for clause in clauses]
    terms = tokens(query)
    average = sum(sum(doc.values()) for doc in documents) / max(len(documents), 1)
    results = []
    for clause, doc in zip(clauses, documents):
        score = 0.0
        for term in terms:
            frequency = doc[term]
            df = sum(term in other for other in documents)
            idf = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5))
            if frequency:
                score += (
                    idf
                    * frequency
                    * 2.2
                    / (frequency + 1.2 * (0.25 + 0.75 * sum(doc.values()) / max(average, 1)))
                )
        results.append((clause, round(score, 6)))
    results.sort(key=lambda item: (-item[1], item[0].intent != intent, item[0].chunk_id))
    return results[:top_k], [
        {"chunk_id": clause.chunk_id, "score": score, "selected": index < top_k}
        for index, (clause, score) in enumerate(results)
    ]


def indexed_clauses(session, policy, clauses, intent):
    # Current policy tenant/status/effective period have already been filtered in SQL.
    rows = session.scalars(
        select(PolicyChunk).where(
            PolicyChunk.tenant_id == policy.tenant_id,
            PolicyChunk.policy_version == policy.id,
            PolicyChunk.intent.in_([intent, "ALL"]),
        )
    ).all()
    expected = {(c.chunk_id, c.intent, c.text) for c in clauses}
    if {(row.chunk_id, row.intent, row.text) for row in rows} != expected:
        raise unavailable("POLICY_INDEX_STALE")
    return clauses


def rebuild_index(session):
    # Trusted seed/CLI transaction only, no model tool or HTTP mutation endpoint.
    session.execute(delete(PolicyChunk))
    policies = session.scalars(select(Policy)).all()
    for policy in policies:
        for clause in policy.clauses:
            session.add(
                PolicyChunk(
                    policy_version=policy.id,
                    tenant_id=policy.tenant_id,
                    chunk_id=clause["chunk_id"],
                    intent=clause["intent"],
                    text=clause["text"],
                )
            )
    session.flush()
    return sum(len(policy.clauses) for policy in policies)
