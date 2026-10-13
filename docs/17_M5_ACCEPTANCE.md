# M5 实施前完成条件（2026-10-12）

用户选择“更强调流程：左侧业务列表，右侧详情与时间线”。范围为React + TypeScript本地前端，客户会话/事件/政策引用/订单/客户确认，员工客服/审核/收货/模拟退款查询，轮询与刷新恢复。M6打包、真实支付、部署不在本阶段。

- 真实接口和后端状态驱动界面，不能写假成功、假余额或前端角色授权；只有后端确认摘要能用于客户点击确认。
- 客户确认、审核员批准、仓库收货使用独立角色session。常规退货必须收货；损坏免退回须明确人工决定。
- 写请求具备稳定幂等键和在途锁；网络结果未知时复用同键，刷新或重复点击不制造第二笔操作。过期/版本冲突显示错误并重新读取状态。
- 会话和run在PostgreSQL持久化；前端恢复已选会话、轮询run和事件，呈现等待/失败/取消。引用/业务数据仅作文本，不能执行HTML或系统指令。
- 后端补齐最小授权列表和业务时间线；客户只能本人的资源，员工限本租户。新增列表不扩充原写权限；确认/审核/退款不添加Agent工具。
- 批量worker仍使用CLI，另提供可信本地常驻轮询方式供演示；没有任意用户HTTP退款执行接口。模拟超时和worker重启在独立测试库演示，不重置现有开发库。
- 桌面/窄屏、键盘、空/加载/错误状态可用；三段真实浏览器演示（普通退货、损坏补问、超时与恢复）覆盖刷新/重复/隔离。
- npm锁文件、TypeScript构建、必要真实PostgreSQL回归及浏览器检查通过后才能标记完成；更新合同、README、DECISIONS和PROJECT_STATUS，保留M0–M4历史证据。

状态：已验收，2026-10-12。机器汇总artifacts/m5/verification.json为PASS。

## 实际交付

React + TypeScript流程工作台：订单/政策、会话/引用/工具事件、真实申请/工单、后端确认摘要、独立客户确认与提交、审核依据及批准/拒绝、仓库收货、模拟流水与未知故障状态。桌面双栏分别滚动，390px切换列表/详情。身份令牌仅短期本地sessionStorage，供应商密钥留在后端。所有业务数据使用React文本渲染。

新增六个只读发现接口及真实PostgreSQL权限/过滤/分页测试；原订单最大20分页不放宽，新申请/工单/会话最大50。CLI新增--watch / --poll-seconds常驻轮询，原单批次worker行为保留；故障注入仍仅可信CLI。

API api-v1-m5、应用/frontend 0.6.0；schema 0005_m4、tools-v2-m4、prompt-v5-m4、fixtures/policy/eval保持原值。M4冻结的prompt/agent/model/grounding四个文件SHA256逐一一致；M4历史报告不覆盖，本阶段没有重新声称独立模型泛化成绩。

## 执行与证据

| 检查 | 实际结果 | 证据 |
|---|---|---|
| M0–M5真实PostgreSQL回归 | 308 passed，311.17秒；M5新增15项 | artifacts/m5/pytest.xml |
| TypeScript/生产构建/格式 | npm run build及format:check通过 | frontend/dist、package-lock.json；本轮工具输出 |
| 真实浏览器与模型流程 | 2测试通过，83.013秒；5个live run，另2个取消run | browser_results.json、browser_trace.json |
| 普通退货 | C-A1→E-A2→E-A3，149元模拟退款唯一 | browser_workflows.json、browser_database.json |
| 损坏澄清 | 多订单先补问，O-A102证据后申请，审核员明确免退回，399元 | 同上 |
| 超时与恢复 | C-A2/O-A108，99元支付已处理但响应超时；UI未知，5秒后新进程查询成功 | timeout-pending.png、browser_trace.json |
| 资金与隔离 | 3笔本地流水=3笔模拟提供方操作，总64700分；客户/跨租户阻断，开发库不变 | browser_database.json |
| 刷新/重复/网络回执丢失 | 刷新恢复摘要及会话；重复确认/批准/收货/worker无重复业务；已提交但丢回执的消息用同键恢复 | browser_recovery.json |
| 停止/安全文本/键盘/窄屏 | 2个run停止，无业务回滚承诺；恶意HTML纯文本；原生控件键盘可操作；390px无横向溢出 | browser_recovery.json、mobile-case.png |
| 合同与旧评测实现 | 实际OpenAPI对账、10工具不变、M4四个实现哈希不变 | docs/contracts/m5_*.json、verification.json |

执行命令：项目根目录 `.venv/Scripts/python.exe -m pytest -q --tb=short --junitxml=artifacts/m5/pytest.xml`；frontend目录 `npm run build`、`npm run format:check`；根目录 `.venv/Scripts/python.exe scripts/browser_m5.py`、`scripts/verify_m5.py`。浏览器脚本使用系统Edge，after_sales_test独立UUID schema，结束时只清理自己创建的schema与子进程。

首轮浏览器脚本错误为未等待异步身份恢复；第二轮在POST收到回执前主动刷新，HTTP尚未确认受理。两份失败报告保留browser_results_initial_failure.json / browser_results_refresh_failure.json；随后改为等真实202后刷新，并额外用真实后端受理后中断回执测试网络未知路径。新增测试初版误填政策外键的失败XML也保留pytest_initial_fixture_failure.xml；正确使用实际种子政策后全量通过。没有把失败改成成功或把取消run计为live成绩。

## 限制与后续

M5只本地模拟，未做生产鉴权/证据上传/真实支付/对外部署/SSE。会话展示后端最近50条消息，本轮工具事件最多100条；长历史分页留待有需求时扩展。sessionStorage恢复限同一浏览器标签页，过期需重新登录；已提交业务状态始终可从列表找回。停run不撤销已完成工具操作。冻结业务时钟与实际审计时钟分开显示，均转换上海时间。M4自由文本引用支撑不足的已知语义限制保留，前端不改变该结果。

M6干净安装、全新数据库与最终交付打包尚未执行。截图为功能验收及两轮界面复核，不是演示录屏；不声称已交付录屏或无障碍认证。
