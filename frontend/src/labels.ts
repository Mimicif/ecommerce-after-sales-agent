export const statusLabels: Record<string, string> = {
  DRAFT: "待核对草稿",
  WAITING_FOR_USER: "待客户确认",
  PENDING_REVIEW: "待人工审核",
  AWAITING_RETURN: "待仓库收货",
  READY_TO_REFUND: "待模拟退款",
  REFUND_PENDING: "模拟退款处理中",
  MANUAL_INTERVENTION: "待人工对账",
  REFUNDED: "模拟退款成功",
  REJECTED: "审核未通过",
  CANCELLED: "已取消",
  DELIVERED: "已签收",
  IN_TRANSIT: "运输中",
  OPEN: "人工处理中",
  QUEUED: "等待处理",
  RUNNING: "正在查询与处理",
  SUCCEEDED: "处理完成",
  COMPLETED: "本轮完成",
  WAITING_FOR_INPUT: "待补充",
  FAILED: "本轮未完成",
};
export const typeLabels: Record<string, string> = {
  RETURN_REFUND: "普通退货",
  DAMAGE_REFUND: "商品损坏",
  LOGISTICS: "物流核查",
  MANUAL_AFTER_SALES: "人工售后",
};
export const eventLabels: Record<string, string> = {
  CREATE_DRAFT: "创建售后草稿",
  CREATE_CONFIRMATION: "生成确认摘要",
  CUSTOMER_CONFIRM: "客户确认",
  SUBMIT_CASE: "提交人工审核",
  REVIEW_CASE: "人工审核",
  RETURN_RECEIVED: "仓库确认收货",
  REFUND_SUCCEEDED: "模拟退款对账成功",
  REQUEST_RECONCILE: "请求重新对账",
  EDIT_DRAFT: "修改草稿",
  CANCEL_CASE: "取消申请",
  REFUND_PENDING: "进入模拟退款队列",
  REFUND_RETRY: "模拟支付结果待查询",
  REFUND_MANUAL: "转人工对账",
  COMPLETED: "本轮完成",
  FAILED: "本轮未完成",
  CANCELLED: "本轮已停止",
  QUEUED: "任务已受理",
  MODEL_RESULT: "分析与选择下一步",
  TOOL_RESULT: "查询或业务操作结果",
  WAITING_FOR_USER: "等待客户",
  FINAL_REPAIR: "核查回复依据",
  RUNNING: "开始处理",
  SUCCEEDED: "本轮完成",
};
export const toolLabels: Record<string, string> = {
  list_my_orders: "查询可访问订单",
  get_order: "读取订单",
  get_logistics: "查询物流",
  search_policy: "查询适用政策",
  check_eligibility: "核验售后资格",
  create_case_draft: "建立待确认草稿",
  get_case: "读取申请状态",
  submit_case: "提交已确认申请",
  create_support_ticket: "建立人工工单",
  get_support_ticket: "读取人工工单",
};
export const money = (fen: number) =>
  new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(
    fen / 100,
  );
export const date = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(value))
    : "暂无时间记录";
export const label = (value: string) =>
  statusLabels[value] ?? typeLabels[value] ?? value;
