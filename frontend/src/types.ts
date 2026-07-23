export type UserRole = "customer" | "support" | "admin";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export interface Citation {
  label: string;
  document_id: string;
  chunk_id: string;
  title: string;
  version: string;
  section_path: string[];
  page: number | null;
  excerpt: string;
}

export interface ChatResponse {
  conversation_id: string;
  message_id: string;
  answer: string;
  intent: string;
  citations: Citation[];
  requires_human: boolean;
  human_reason: string | null;
  suggested_actions: string[];
  ticket_code: string | null;
  warranty_assessment:
    | "eligible"
    | "ineligible"
    | "needs_manual_review"
    | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  intent: string | null;
  citations: Citation[];
  requires_human: boolean;
  human_reason: string | null;
  suggested_actions: string[];
  ticket_code: string | null;
  warranty_assessment:
    | "eligible"
    | "ineligible"
    | "needs_manual_review"
    | null;
  created_at: string;
  pending?: boolean;
  failed?: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[];
}

export type FeedbackRating = "positive" | "negative";

export type DocumentStatus =
  | "uploaded"
  | "processing"
  | "ready"
  | "published"
  | "failed"
  | "archived";

export interface KnowledgeDocument {
  id: string;
  title: string;
  version: string;
  category: string;
  source_filename: string;
  media_type: string;
  checksum: string;
  language: string;
  status: DocumentStatus;
  effective_from: string | null;
  effective_to: string | null;
  published_at: string | null;
  failure_reason: string | null;
}

export interface EscalationReview {
  conversation_id: string;
  title: string | null;
  human_reason: string | null;
  ticket_code: string | null;
  raised_at: string;
}

export interface ControlledReviewMessage {
  role: "user" | "assistant";
  content: string;
  created_at: string;
  requires_human: boolean;
  human_reason: string | null;
}

export interface TicketReview {
  ticket_code: string;
  conversation_id: string | null;
  category: string;
  subject: string;
  summary: string;
  status: "open" | "in_review" | "resolved";
  severity: "normal" | "high" | "critical";
  created_at: string;
}

export interface OperationsMetrics {
  chat: {
    latency: {
      count: number;
      p95_ms: number;
    };
    human_escalation_rate: number;
    tickets_created: number;
  };
  rag: {
    requests?: number;
    no_result?: number;
  };
}
