export interface Identity {
  user_id: string;
  tenant_id: string;
  roles: string[];
  business_now: string;
}
export interface Session {
  access_token: string;
  user_id: string;
  expires_at: string;
}
export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}
export interface Order {
  id: string;
  status: string;
  product_category: string;
  paid_amount_fen: number;
  refunded_amount_fen: number;
  delivered_at: string | null;
  cases: { id: string; status: string; version: number }[];
}
export interface Case {
  id: string;
  order_id: string;
  case_type: string;
  status: string;
  version: number;
  requested_amount_fen: number;
  reason: string;
  evidence_refs: string[];
  policy_version: string;
  review_required: boolean;
}
export interface Ticket {
  id: string;
  order_id: string;
  status: string;
  category: string;
  summary: string;
}
export interface Conversation {
  conversation_id: string;
  created_at: string;
}
export interface Message {
  message_id: string;
  role: string;
  content: string;
  run_id: string | null;
  seq: number;
}
export interface Run {
  run_id: string;
  conversation_id: string;
  action: string;
  status: string;
  error_code: string | null;
  response: {
    answer: string;
    citations: string[];
    cases: Case[];
    tickets: Ticket[];
  } | null;
}
export interface Event {
  seq: number;
  kind: string;
  created_at: string;
  data: Record<string, unknown>;
}
export interface Timeline {
  id: string;
  action: string;
  result: string;
  occurred_at: string;
  summary: { status?: string; amount_fen?: number; version?: number };
}
export interface Refund {
  status: string;
  funds_state: string;
  transaction: {
    provider_operation_id: string;
    amount_fen: number;
    status: string;
  } | null;
  job: { status: string; attempts: number; last_error: string | null } | null;
}
export interface Confirmation {
  confirmation_id: string;
  payload_digest: string;
  expires_at: string;
  summary: Case & { notice: string };
}
export interface Evidence {
  id: string;
  kind: string;
  description: string;
}
export interface Policy {
  policy_version: string;
  clauses: { chunk_id: string; text: string; citation: string }[];
}
