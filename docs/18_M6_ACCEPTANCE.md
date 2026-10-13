# M6 本地交付验收（2026-10-12）

## 开发前完成条件

1. README 按当前 0.6.0 实际接口说明安装、迁移、种子、四进程启动及停止；架构图与实现一致。
2. 从源码包解压到新目录，使用 uv.lock / package-lock.json 创建全新依赖目录，生产构建成功。
3. 创建独立且从未使用的 PostgreSQL 数据库，迁移到 head、Alembic check、两次种子导入通过。
4. 干净目录的完整后端回归通过；生产前端在新数据库完成三个剧本、刷新与重复操作、权限隔离、超时恢复。
5. 留下真实操作录屏、步骤时间表、机器报告、源码清单及 SHA256。源码包排除凭据、依赖、数据库和运行日志。
6. M4 原始成功/失败成绩与冻结实现保持；M5 历史证据保留；不把本次演示称为新的独立泛化评测。

当前状态：已通过（2026-10-12执行，2026-10-13最终交接）。机器报告见artifacts/m6/verification.json；最终源码包另附SHA256、每文件清单和包核验报告。


## 过程记录与展示修复

首轮干净安装/生产构建/新物理库迁移及重复seed成功，回归307通过1失败：验收进程把fixture时钟传给全体pytest，test_reset_guard关闭DEV_MODE时按设计拒绝。修正验收环境为system，浏览器仍fixture；artifacts/m6_initial_clock_failure保留原始失败与数据库清理证据。

第二轮完整308项回归通过（402.22秒），两项浏览器测试及3笔唯一模拟退款通过；原录屏228.72秒。视觉复核发现前端直接展示ChatMessage.content中的模型记忆后缀。该后缀由后端主动附加，不是模型隐藏推理；用户明确选择修复展示层并重录。原成绩和录像保存在artifacts/m6_before_display_fix，不作为最终录屏。

展示修复版本m6-memory-projection-v1：仅assistant消息末尾符合固定标记、合法JSON且恰含cases/tickets数组的记忆后缀隐藏；用户输入不裁剪，普通文本/无效后缀不裁剪。申请卡/权限/金额/状态仍由后端确定。该展示修复未改后端、冻结Agent/prompt、检索或模型实现；之后的持久化修复单独记录，M4原评测适用范围不扩大。

第三轮从新源码包重新干净安装、全新物理库和生产构建，新增浏览器断言：刷新后Agent正文无内部后缀，客户同样格式原文完整保留，关联申请卡与多轮流程继续有效。完整308项后端回归通过后台代码/data/evals/锁文件集合哈希核验后沿用第二轮证据，未为纯前端修复无目的重跑后台；最终报告明确记录来源，不把沿用计为新增执行。


## 重录暴露的 checkpoint 竞态（用户已授权修复）

第三轮新浏览器第一项失败，第二项网络/安全文本检查通过。失败run在损坏草稿工具成功后，checkpoint pending write触发graph_writes_run_id_checkpoint_id_fkey（SQLSTATE23503）；真实PG日志确认父checkpoint尚未插入。LangGraph后台future保存并不保证这两个事务的提交先后，run行fence只能串行化访问而非建立父子保存顺序。

用户已选择“修复竞态并继续验收”。checkpoint-v2-m6在短事务中核验lease/budget及父checkpoint；未存在时释放run行锁后最多等待2秒，有父记录后才提交write。超时返回安全错误RUN_CHECKPOINT_NOT_READY，不写孤儿、不放宽外键、不重置run预算；每次重试重新核验租约。新增真实PG的强制保存先后颠倒、无父记录超时、等待中租约失效三项回归。修复前强制顺序测试确实触发相同外键错误，证据保留在artifacts/m6_checkpoint_race_failure/forced_order_before_fix.xml。

该持久化组件不属于M4四文件冻结集合；四文件与数据集哈希仍须核验，原M4成绩仅描述当时实现。本次改动另以checkpoint版本/源码哈希和311项完整回归验证，不沿用纯前端修复时的后台成绩，不宣称新增独立模型泛化评测。完整第三轮失败和trace、清理记录保存在artifacts/m6_checkpoint_race_failure；M6等待新候选验收。

定向验证：修复后checkpoint相关7项通过（9.86秒），包含三条新增真实PG回归及既有持久化/崩溃恢复/旧租约拒绝路径；XML见artifacts/m6_checkpoint_race_failure/checkpoint_after_fix.xml。第四轮候选源码SHA256=b6dc84f3d00f28fa5f2baedf178d618dbc4f09991a5097e0ef6e1d8a5b93f797，重新创建依赖和物理数据库并完整执行，不使用后台报告复用选项。

## 最终结果

| 完成条件 | 实际证据 |
|---|---|
| 当前安装/启动/架构说明 | README、02_ARCHITECTURE、04_API_TOOLS、ADR-019/020；Windows四进程命令与限制 |
| 干净安装与锁文件 | 解压candidate4到独立目录，初始无.env/venv/node_modules，uv sync --locked及npm ci/生产build/format成功；仅复用下载缓存 |
| 全新数据库 | 独立after_sales_m6_UUID物理库，普通应用角色；迁移head、check、两次seed通过；结束已清理；完整pytest仍使用after_sales_test独立schema |
| 完整后台 | 311 passed，0 failed/errors/skipped，342.53秒；进程步骤353.015秒；新增3条PG回归 |
| 生产浏览器与live模型 | 两项Edge测试通过，242.957秒；5个deepseek-flash run及2取消run；三个REFUNDED申请/唯一流水/提供方操作，共64700分 |
| 恢复/授权/文本 | UNKNOWN后新worker查询恢复、重复操作/刷新、跨用户/租户/角色、网络回执丢失同键恢复、用户HTML及后缀原文、键盘与390px通过；开发库不变 |
| 录像与视觉复核 | 228.2秒，1366×900；聊天90秒帧不含内部记忆后缀；待对账截图与恢复后手机截图、客服权限截图正确；visual_review.json记录抽样范围 |
| 版本与可追溯 | 1124个已测核心文件hash一致；M4冻结四文件/数据集、API/十工具一致；新checkpoint版本及hash单独记录；原成绩/失败保留 |

所有十二个干净复现步骤exit_code=0；最终机器核验PASS。源码包dist/after-sales-agent-0.6.0-local-m6.zip包含RELEASE_MANIFEST.json；配套.sha256及.verification.json在同目录。视频artifacts/m6/demo.webm独立交付，不进入ZIP；包排除.env、私有数据库凭据、依赖、数据库与原始日志，实际凭据扫描通过。最终包中的核心代码须与candidate4逐文件一致，允许补充交接文档与报告。

实测环境：Python3.12.7、uv0.12.0、Node24.14.1、npm11.11.0、PostgreSQL18.6、系统Edge；Python/npm依赖以锁文件为准。旧PRODUCT/DESIGN保留M5产品输入基线，最终阶段状态以PROJECT_STATUS和本报告为准。

未覆盖生产认证/外部支付/公网部署/上传证据或自动鉴定，也未新增独立模型泛化评测；M4已记录的自然语言引用限制仍存在。当前本地工作台2026-10-13恢复后8000/5173均HTTP200。M6按本地模拟范围完成，不承诺生产可用。
