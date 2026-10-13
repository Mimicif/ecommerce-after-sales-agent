# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

主要为商家客服；演示包含客户、独立审核员和仓库。本地开发人员与面试评审通过完整流程核验后端和Agent能力。

## Product Purpose

将物流、退货、损坏诉求变成可审计的售后处理过程，展示真实权限、确认、审批、模拟支付恢复及模型评测。

## Operating Context

Windows本地浏览器，React + TypeScript、FastAPI与PostgreSQL。业务Clock可冻结为fixtures；金额为整数分，展示Asia/Shanghai。消息与状态使用轮询。

## Capabilities and Constraints

仅模拟订单、政策、证据引用和支付，没有生产鉴权或真实支付。客户确认不等于人工批准；常规退货批准后必须仓库收货。Agent没有审核/收货/资金执行权限。独立角色session，后端资源鉴权是最终边界。M0–M5已验收，M6交付复现待执行。

## Brand Commitments

2026-10-12用户明确选择流程布局：左侧业务列表，右侧详情与时间线。文案中文，模拟支付明确标识，业务任务优先。

## Evidence on Hand

docs/01_PRD.md、03_DOMAIN_RULES.md、11_DEMO_RESUME.md、16_M4_ACCEPTANCE.md；data/fixtures.json与policy.json为模拟数据；M0–M4原始测试/模型失败与成功记录保留。没有真实客户、商业收益或运营数据。

## Product Principles

- 所有金额、身份、状态与业务权限由后端确定。
- 可看到当前真实状态、下一步责任人和失败恢复路径。
- 模型回复与持久化业务状态分别展示。
- 重复点击与刷新不能制造重复业务效果。
