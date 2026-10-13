---
name: 流程 · 售后工作台
description: 左侧业务列表，右侧事实、下一步责任人与时间线。
colors:
  primary: "#225f4a"
  paper: "#ffffff"
  canvas: "#f3f5f3"
  sidebar: "#f5f7f4"
  foreground: "#202d2b"
  muted: "#66746e"
  border: "#d9dfdc"
  soft: "#edf3ef"
typography:
  body:
    fontFamily: 'Inter, "Segoe UI", "Microsoft YaHei", sans-serif'
    fontSize: "14px"
    lineHeight: 1.65
  heading:
    fontSize: "30px"
    fontWeight: 650
    lineHeight: 1.35
rounded:
  control: "5px"
  badge: "3px"
spacing:
  detail-x: "48px"
  detail-y: "38px"
  mobile: "20px"
components:
  primary-button:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    padding: "9px 15px"
---

## Overview

Operate界面，按用户确认的流程布局实现。以可信业务状态为中心，模型回复与后端申请详情分开。无虚构指标、余额、业绩或真实支付承诺。来源为frontend/src/styles.css与实际桌面/390px浏览器截图。

## Colors

白纸正文、浅灰绿侧栏、森林绿主要操作。灰色表示等待，浅绿表示已核对的成功；错误与待核查使用浅红/浅黄背景并带文本说明，不能只靠颜色传达。

## Typography

单一无衬线字体栈，无外部字体请求；Windows回退为Segoe UI及微软雅黑。标题30/18px，正文14px，标签/辅助文字12/11px。资源ID用小号等宽字，业务说明允许换行；金额由整数分格式化。

## Layout

桌面72px身份栏、310px列表与详情双栏；1000px以下侧栏270px。列表和详情分别滚动，长时间线不挤掉业务导航。650px以下列表/详情切换，提供返回按钮；390px实测无横向溢出。详情38px纵向/48px横向留白，窄屏20px。

## Elevation & Depth

使用分隔线与背景层次，不使用投影和渐变。确认与审核在详情内展开，不用模态框遮住业务事实。

## Shapes

控件5px圆角，状态标识3px。原生select/textarea/checkbox，最小42px按钮，3px可见键盘焦点。选中记录、错误、等待和下一步面板的细侧线承担状态语义。

## Components

订单/申请/会话/工单列表、身份栏、后端确认摘要、独立角色操作区、模拟退款结果、业务时间线、会话输入和可审计步骤。输入有长度约束、在途锁与错误提示；模拟未知退款保持“处理中”，仅实际后端流水允许成功。运行中的会话可停止，取消不回滚已提交业务操作。

## Do's and Don'ts

- 延续用户指定的双栏业务流程及中文文案，金额、政策、责任角色须有真实后端来源。
- 模拟支付持续标识，不把模型建议转换为资金成功状态，不添加万能身份。
- 检测器于本轮运行一次：4条侧线及1条字体警告按Operate语境保留。侧线分别表示错误、选中列表、下一步操作和等待状态；字体栈是本地熟悉的产品字体，未加载外部Inter。这些是已复核的设计选择，非安全/功能失败。
- 本轮已批量复核桌面与窄屏并一次修正滚动、状态标签和工具名称；第二轮确认后停止视觉微调。遵守项目限制，由本线程复核，无子Agent。
