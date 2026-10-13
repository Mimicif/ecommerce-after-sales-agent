# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: workflow.spec.ts >> 真实模型 / 普通退货、损坏澄清、支付超时恢复与角色隔离
- Location: e2e\workflow.spec.ts:145:1

# Error details

```
Error: expect(locator).toHaveCount(expected) failed

Locator:  locator('.message.assistant')
Expected: 2
Received: 1
Timeout:  60000ms

Call log:
  - Expect "toHaveCount" locator('.message.assistant') with timeout 60000ms
  - waiting for locator('.message.assistant')
    2 × locator resolved to 0 elements
      - unexpected value "0"
    119 × locator resolved to 1 element
        - unexpected value "1"

```

# Page snapshot

```yaml
- generic [ref=f9e2]:
  - banner [ref=f9e3]:
    - link "流程售后工作台" [ref=f9e4] [cursor=pointer]:
      - /url: /
    - generic [ref=f9e5]: 本地模拟 · 10/11 10:00
    - generic [ref=f9e6]:
      - generic [ref=f9e7]: TENANT-A / 客户 · C-A1
      - button "切换身份" [ref=f9e8] [cursor=pointer]
  - main [ref=f9e9]:
    - complementary "业务列表" [ref=f9e10]:
      - generic [ref=f9e11]:
        - paragraph [ref=f9e12]: 工作区
        - heading "客户与业务" [level=1] [ref=f9e13]
      - navigation "业务类型" [ref=f9e14]:
        - button "订单" [ref=f9e15] [cursor=pointer]
        - button "申请" [ref=f9e16] [cursor=pointer]
        - button "会话" [ref=f9e17] [cursor=pointer]
        - button "工单" [ref=f9e18] [cursor=pointer]
      - button "＋ 新建咨询会话" [ref=f9e19] [cursor=pointer]
      - generic [ref=f9e20]:
        - button "O-A101 ¥149.00 已签收 查看订单与适用政策" [ref=f9e21] [cursor=pointer]:
          - generic [ref=f9e22]: O-A101
          - generic [ref=f9e23]: ¥149.00
          - generic [ref=f9e24]: 已签收
          - generic [ref=f9e25]:
            - text: 查看订单与适用政策
            - generic [aria-hidden] [ref=f9e26]: ↗
        - button "O-A102 ¥399.00 已签收 查看订单与适用政策" [ref=f9e27] [cursor=pointer]:
          - generic [ref=f9e28]: O-A102
          - generic [ref=f9e29]: ¥399.00
          - generic [ref=f9e30]: 已签收
          - generic [ref=f9e31]:
            - text: 查看订单与适用政策
            - generic [aria-hidden] [ref=f9e32]: ↗
        - button "O-A103 ¥89.00 已签收 查看订单与适用政策" [ref=f9e33] [cursor=pointer]:
          - generic [ref=f9e34]: O-A103
          - generic [ref=f9e35]: ¥89.00
          - generic [ref=f9e36]: 已签收
          - generic [ref=f9e37]:
            - text: 查看订单与适用政策
            - generic [aria-hidden] [ref=f9e38]: ↗
        - button "O-A104 ¥99.00 运输中 查看订单与适用政策" [ref=f9e39] [cursor=pointer]:
          - generic [ref=f9e40]: O-A104
          - generic [ref=f9e41]: ¥99.00
          - generic [ref=f9e42]: 运输中
          - generic [ref=f9e43]:
            - text: 查看订单与适用政策
            - generic [aria-hidden] [ref=f9e44]: ↗
        - button "O-A105 ¥129.00 运输中 查看订单与适用政策" [ref=f9e45] [cursor=pointer]:
          - generic [ref=f9e46]: O-A105
          - generic [ref=f9e47]: ¥129.00
          - generic [ref=f9e48]: 运输中
          - generic [ref=f9e49]:
            - text: 查看订单与适用政策
            - generic [aria-hidden] [ref=f9e50]: ↗
        - button "O-A106 ¥299.00 已签收 查看订单与适用政策" [ref=f9e51] [cursor=pointer]:
          - generic [ref=f9e52]: O-A106
          - generic [ref=f9e53]: ¥299.00
          - generic [ref=f9e54]: 已签收
          - generic [ref=f9e55]:
            - text: 查看订单与适用政策
            - generic [aria-hidden] [ref=f9e56]: ↗
        - button "O-A107 ¥199.00 已签收 查看订单与适用政策" [ref=f9e57] [cursor=pointer]:
          - generic [ref=f9e58]: O-A107
          - generic [ref=f9e59]: ¥199.00
          - generic [ref=f9e60]: 已签收
          - generic [ref=f9e61]:
            - text: 查看订单与适用政策
            - generic [aria-hidden] [ref=f9e62]: ↗
        - button "O-A109 ¥109.00 已签收 查看订单与适用政策" [ref=f9e63] [cursor=pointer]:
          - generic [ref=f9e64]: O-A109
          - generic [ref=f9e65]: ¥109.00
          - generic [ref=f9e66]: 已签收
          - generic [ref=f9e67]:
            - text: 查看订单与适用政策
            - generic [aria-hidden] [ref=f9e68]: ↗
        - button "O-A110 ¥0.00 已签收 查看订单与适用政策" [ref=f9e69] [cursor=pointer]:
          - generic [ref=f9e70]: O-A110
          - generic [ref=f9e71]: ¥0.00
          - generic [ref=f9e72]: 已签收
          - generic [ref=f9e73]:
            - text: 查看订单与适用政策
            - generic [aria-hidden] [ref=f9e74]: ↗
        - button "O-A111 ¥119.00 已签收 查看订单与适用政策" [ref=f9e75] [cursor=pointer]:
          - generic [ref=f9e76]: O-A111
          - generic [ref=f9e77]: ¥119.00
          - generic [ref=f9e78]: 已签收
          - generic [ref=f9e79]:
            - text: 查看订单与适用政策
            - generic [aria-hidden] [ref=f9e80]: ↗
        - button "O-A112 ¥200.00 已签收 查看订单与适用政策" [ref=f9e81] [cursor=pointer]:
          - generic [ref=f9e82]: O-A112
          - generic [ref=f9e83]: ¥200.00
          - generic [ref=f9e84]: 已签收
          - generic [ref=f9e85]:
            - text: 查看订单与适用政策
            - generic [aria-hidden] [ref=f9e86]: ↗
        - button "O-A113 ¥159.00 运输中 查看订单与适用政策" [ref=f9e87] [cursor=pointer]:
          - generic [ref=f9e88]: O-A113
          - generic [ref=f9e89]: ¥159.00
          - generic [ref=f9e90]: 运输中
          - generic [ref=f9e91]:
            - text: 查看订单与适用政策
            - generic [aria-hidden] [ref=f9e92]: ↗
      - generic [ref=f9e93]: 模拟支付 · 无真实资金流转业务时间由后端提供
    - region "业务详情" [ref=f9e94]:
      - generic [ref=f9e95]:
        - generic [ref=f9e96]:
          - generic [ref=f9e97]:
            - paragraph [ref=f9e98]: 客户会话
            - heading "先核对，再行动。" [level=1] [ref=f9e99]
            - paragraph [ref=f9e100]: CONV-27986F4D12504BA2BB3C684E4B075497
          - generic [ref=f9e101]: 本轮未完成
        - generic "会话消息" [ref=f9e102]:
          - article [ref=f9e103]:
            - text: 客户输入
            - paragraph [ref=f9e104]: 商品破损了，想申请售后，我需要补充什么？
          - article [ref=f9e105]:
            - text: Agent 回复
            - paragraph [ref=f9e106]: 您有多个订单，请先告诉我目标订单号（例如 O-A101、O-A102 等）。另外，破损售后需要补充：1）破损部位和现象的具体描述；2）有效证据引用（evidence_refs）。请一并提供，我再为您核查该订单的损坏退款资格。
          - article [ref=f9e107]:
            - text: 客户输入
            - paragraph [ref=f9e108]: O-A102 商品已损坏，证据 EVIDENCE-A1。我明确申请损坏退款，请建立草稿。
        - paragraph [ref=f9e109]: 本轮未完成（RUN_INTERNAL_ERROR）。请读取业务状态后再决定下一步。
        - generic [ref=f9e110]:
          - generic [ref=f9e111]:
            - generic [ref=f9e112]:
              - text: 订单
              - combobox "会话订单" [ref=f9e113]:
                - option "请选择订单"
                - option "O-A101 · ¥149.00"
                - option "O-A102 · ¥399.00" [selected]
                - option "O-A103 · ¥89.00"
                - option "O-A104 · ¥99.00"
                - option "O-A105 · ¥129.00"
                - option "O-A106 · ¥299.00"
                - option "O-A107 · ¥199.00"
                - option "O-A109 · ¥109.00"
                - option "O-A110 · ¥0.00"
                - option "O-A111 · ¥119.00"
                - option "O-A112 · ¥200.00"
                - option "O-A113 · ¥159.00"
            - generic [ref=f9e114]:
              - text: 本轮操作
              - combobox "本轮操作" [ref=f9e115]:
                - option "仅咨询"
                - option "申请售后（先建草稿）" [selected]
                - option "同意建立人工工单"
                - option "提交已确认申请"
          - generic [ref=f9e116]:
            - text: 问题或补充说明
            - textbox "问题或补充说明" [ref=f9e117]:
              - /placeholder: 例如：这笔订单想退货，请先检查适用规则。
          - generic [ref=f9e118]:
            - generic [ref=f9e119]: 可用模拟证据
            - button "＋ EVIDENCE-A1 / SIMULATED_IMAGE_REFERENCE" [ref=f9e120] [cursor=pointer]
          - generic [ref=f9e121]:
            - generic [ref=f9e122]: 0/4000 · 修改业务须人工确认与审核
            - button "发送 →" [disabled] [ref=f9e123]
        - group [ref=f9e124]:
          - generic "本轮可审计步骤 (10)" [ref=f9e125] [cursor=pointer]
```

# Test source

```ts
  1   | import { test, expect, type Page } from "@playwright/test";
  2   | import { spawn, execFileSync } from "node:child_process";
  3   | import { writeFileSync } from "node:fs";
  4   | import { resolve } from "node:path";
  5   | 
  6   | const root = resolve("..");
  7   | const python = resolve(root, ".venv/Scripts/python.exe");
  8   | const artifacts = resolve(
  9   |   root,
  10  |   process.env.BROWSER_ARTIFACT_DIR || "artifacts/m5",
  11  | );
  12  | const demoSteps: { seconds: number; step: string }[] = [];
  13  | let demoStarted = 0;
  14  | async function dwell(page: Page, step: string) {
  15  |   if (process.env.DEMO_RECORD !== "true") return;
  16  |   demoSteps.push({
  17  |     seconds: Math.round((Date.now() - demoStarted) / 1000),
  18  |     step,
  19  |   });
  20  |   await page.waitForTimeout(6000);
  21  | }
  22  | const cases: Record<string, string> = {};
  23  | const pageErrors: string[] = [];
  24  | async function enter(page: Page, user: string) {
  25  |   await page.goto("/");
  26  |   await expect(
  27  |     page
  28  |       .getByRole("button", { name: "进入工作台 →" })
  29  |       .or(page.getByRole("button", { name: "切换身份" })),
  30  |   ).toBeVisible();
  31  |   if (await page.getByRole("button", { name: "切换身份" }).isVisible())
  32  |     await page.getByRole("button", { name: "切换身份" }).click();
  33  |   await page.getByLabel("演示身份").selectOption(user);
  34  |   await page.getByRole("button", { name: "进入工作台 →" }).click();
  35  |   await expect(page.getByRole("button", { name: "切换身份" })).toBeVisible();
  36  |   await dwell(page, `切换独立身份：${user}`);
  37  | }
  38  | async function api(page: Page, path: string) {
  39  |   return page.evaluate(async (path) => {
  40  |     const session = JSON.parse(sessionStorage.getItem("m5:session")!);
  41  |     const response = await fetch("/api/v1" + path, {
  42  |       headers: { Authorization: `Bearer ${session.access_token}` },
  43  |     });
  44  |     return { status: response.status, data: (await response.json()).data };
  45  |   }, path);
  46  | }
  47  | async function chat(page: Page) {
  48  |   await page.getByRole("button", { name: "＋ 新建咨询会话" }).click();
  49  |   await expect(
  50  |     page.getByRole("heading", { name: "先核对，再行动。" }),
  51  |   ).toBeVisible();
  52  | }
  53  | async function send(
  54  |   page: Page,
  55  |   content: string,
  56  |   order?: string,
  57  |   action = "CONSULT",
  58  | ) {
  59  |   const count = await page.locator(".message.assistant").count();
  60  |   if (order) await page.getByLabel("会话订单").selectOption(order);
  61  |   await page.getByLabel("本轮操作").selectOption(action);
  62  |   await page.getByLabel("问题或补充说明").fill(content);
  63  |   const accepted = page.waitForResponse(
  64  |     (r) => r.url().endsWith("/messages") && r.request().method() === "POST",
  65  |   );
  66  |   await page.getByRole("button", { name: "发送 →" }).click();
  67  |   expect((await accepted).status()).toBe(202);
  68  |   await page.reload();
> 69  |   await expect(page.locator(".message.assistant")).toHaveCount(count + 1);
      |                                                    ^ Error: expect(locator).toHaveCount(expected) failed
  70  |   await expect(page.locator(".message.assistant").last()).not.toContainText(
  71  |     "服务端事实（上下文，勿仿写为最终输出格式）：",
  72  |   );
  73  |   await expect(page.getByRole("button", { name: "发送 →" })).toBeVisible();
  74  |   await dwell(page, "刷新后查看真实模型回复与后端状态");
  75  | }
  76  | async function openCase(page: Page, order: string) {
  77  |   await page
  78  |     .getByRole("navigation", { name: "业务类型" })
  79  |     .getByRole("button", { name: "申请", exact: true })
  80  |     .click();
  81  |   await page
  82  |     .locator(".list-row")
  83  |     .filter({ has: page.locator(".row-title", { hasText: order }) })
  84  |     .click();
  85  |   await expect(
  86  |     page.getByRole("heading", { name: "模拟退款结果" }),
  87  |   ).toBeVisible();
  88  |   const response = await api(page, "/cases");
  89  |   cases[order] = response.data.items.find(
  90  |     (c: { order_id: string }) => c.order_id === order,
  91  |   ).id;
  92  | }
  93  | async function confirm(page: Page) {
  94  |   await page.getByRole("button", { name: "生成确认摘要", exact: true }).click();
  95  |   await expect(
  96  |     page.getByRole("button", { name: "确认申请并提交审核" }),
  97  |   ).toBeVisible();
  98  |   await page.reload();
  99  |   await expect(
  100 |     page.getByRole("button", { name: "确认申请并提交审核" }),
  101 |   ).toBeVisible();
  102 |   await page
  103 |     .getByRole("button", { name: "确认申请并提交审核" })
  104 |     .click({ clickCount: 2 });
  105 |   await expect(page.getByText("已提交，等待独立审核员处理。")).toBeVisible();
  106 |   await dwell(page, "客户确认后端摘要并提交；仍需人工审核");
  107 |   await page.reload();
  108 |   await expect(page.getByText("已提交，等待独立审核员处理。")).toBeVisible();
  109 | }
  110 | async function approve(page: Page, order: string, returnRequired = true) {
  111 |   await enter(page, "E-A2");
  112 |   await openCase(page, order);
  113 |   await page
  114 |     .getByLabel("审核依据")
  115 |     .fill("核实模拟申请及证据，按当前政策批准。");
  116 |   if (!returnRequired)
  117 |     await page.getByLabel("要求退回并由仓库确认收货").uncheck();
  118 |   await page
  119 |     .getByRole("button", { name: "批准申请", exact: true })
  120 |     .click({ clickCount: 2 });
  121 |   await expect(
  122 |     page.getByRole("button", { name: "批准申请", exact: true }),
  123 |   ).toHaveCount(0);
  124 |   await dwell(page, "独立审核员审核通过");
  125 | }
  126 | async function receive(page: Page, order: string) {
  127 |   await enter(page, "E-A3");
  128 |   await openCase(page, order);
  129 |   await page
  130 |     .getByRole("button", { name: "确认仓库已收货" })
  131 |     .click({ clickCount: 2 });
  132 |   await expect(
  133 |     page.getByRole("button", { name: "确认仓库已收货" }),
  134 |   ).toHaveCount(0);
  135 |   await dwell(page, "独立仓库确认收货");
  136 | }
  137 | function refund(fault = "success") {
  138 |   execFileSync(
  139 |     python,
  140 |     ["-m", "app.cli", "refund-worker", "--max-jobs", "1", "--fault", fault],
  141 |     { cwd: root, env: process.env, stdio: "pipe", timeout: 30_000 },
  142 |   );
  143 | }
  144 | 
  145 | test("真实模型 / 普通退货、损坏澄清、支付超时恢复与角色隔离", async ({
  146 |   page,
  147 | }) => {
  148 |   demoStarted = Date.now();
  149 |   page.on("pageerror", (e) => pageErrors.push(e.message));
  150 |   const agent = spawn(
  151 |     python,
  152 |     ["-u", "-m", "app.cli", "agent-worker", "--watch", "--poll-seconds", "0.2"],
  153 |     { cwd: root, env: process.env, stdio: "ignore", windowsHide: true },
  154 |   );
  155 |   try {
  156 |     await enter(page, "C-A1");
  157 |     await page.screenshot({
  158 |       path: resolve(artifacts, "desktop-workspace.png"),
  159 |       fullPage: true,
  160 |     });
  161 |     await chat(page);
  162 |     await send(
  163 |       page,
  164 |       "这笔订单不合适，我明确申请普通退货退款，请创建售后草稿。",
  165 |       "O-A101",
  166 |       "APPLY_AFTER_SALES",
  167 |     );
  168 |     await expect(
  169 |       page.getByRole("button", { name: /O-A101 · 普通退货/ }),
```