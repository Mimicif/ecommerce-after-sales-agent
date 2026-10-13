# M0 工程与环境验收合同

日期：2026-10-11；范围：确定性本地后端，不连接模型。

## 完成条件（实施前确定）

1. Windows Python、uv、Git 可用；Docker 或真实 PostgreSQL 至少一项可运行。
2. Python 3.12 工程、uv.lock、隔离环境、无秘密的配置示例齐备。
3. 空 PostgreSQL 可 Alembic 迁移，fixtures/policy 原子导入可重复执行；显式本地重置后恢复相同种子。
4. 健康接口真实探测数据库；开发登录仅 DEV_MODE + loopback，短期随机 session 由后端保存并校验。
5. PostgreSQL 集成测试证明：两个租户隔离、同租户不同客户隔离、员工角色受限、客户端伪造 tenant/roles 无效、过期或篡改 token 无效。
6. 真实 HTTP 启动冒烟通过；README、PROJECT_STATUS 与版本记录同步，证据不保存 session 原文或密码。

## 当前实现边界

API 前缀 `/api/v1`，M0 提前实现最小只读订单列表与详情，仅为验证权限。
物流查询、政策检索、资格引擎属于 M1；写业务与审核退款属于 M2；Agent 属于 M3。
policy.json 导入全部版本的规则和 clauses；policy.md 保留为对照文档，不混合索引其版本说明。
fixture_clock 保存为 UTC 元数据，后续 M1 规则时钟据此注入；session 有效期始终使用真实 UTC 时间。
测试使用独立 after_sales_test 库中的随机 schema，通过真实迁移建立；无 SQLite 和跳过验收。
