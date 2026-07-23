import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUp,
  BookOpenCheck,
  CheckCircle2,
  ChevronRight,
  CircleUserRound,
  FileText,
  History,
  Gauge,
  LogOut,
  Menu,
  MessageSquarePlus,
  PanelRightOpen,
  RotateCcw,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";

import { useAuth } from "../auth-context";
import { ApiError, apiRequest, streamChat } from "../lib/api";
import type {
  ChatMessage,
  ConversationDetail,
  ConversationSummary,
  FeedbackRating,
} from "../types";

const SUGGESTIONS = [
  "Đơn DH2026000001 giao tới đâu rồi?",
  "Serial SN2600000001 còn bảo hành không?",
  "Chính sách đổi trả đang áp dụng thế nào?",
  "Điện thoại Samsung nào đang còn hàng?",
];

function emptyAssistant(id: string): ChatMessage {
  return {
    id,
    role: "assistant",
    content: "",
    intent: null,
    citations: [],
    requires_human: false,
    human_reason: null,
    suggested_actions: [],
    ticket_code: null,
    warranty_assessment: null,
    created_at: new Date().toISOString(),
    pending: true,
  };
}

function userMessage(content: string): ChatMessage {
  return {
    id: `user-${crypto.randomUUID()}`,
    role: "user",
    content,
    intent: null,
    citations: [],
    requires_human: false,
    human_reason: null,
    suggested_actions: [],
    ticket_code: null,
    warranty_assessment: null,
    created_at: new Date().toISOString(),
  };
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  }).format(new Date(value));
}

function actionLabel(action: string): string {
  if (action === "confirm_ticket_creation") return "Đồng ý tạo ticket";
  if (action === "contact_support") return "Chuyển nhân viên hỗ trợ";
  return "Tiếp tục hỗ trợ";
}

function actionMessage(action: string): string {
  if (action === "confirm_ticket_creation") return "Đồng ý tạo ticket";
  return "Hãy chuyển tôi tới nhân viên hỗ trợ.";
}

function warrantyAssessmentLabel(
  value: ChatMessage["warranty_assessment"],
): string {
  if (value === "eligible") return "Đủ điều kiện tiếp nhận sơ bộ";
  if (value === "ineligible") return "Không đủ điều kiện theo thời hạn";
  return "Cần kiểm tra thủ công";
}

export function ChatPage() {
  const { token, user, logout } = useAuth();
  const queryClient = useQueryClient();
  const [activeConversationId, setActiveConversationId] = useState<string | null>(
    null,
  );
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [localMessagesActive, setLocalMessagesActive] = useState(false);
  const [composer, setComposer] = useState("");
  const [sending, setSending] = useState(false);
  const [requestError, setRequestError] = useState("");
  const [feedbackSentId, setFeedbackSentId] = useState<string | null>(null);
  const [mobileLedgerOpen, setMobileLedgerOpen] = useState(false);
  const [mobileEvidenceOpen, setMobileEvidenceOpen] = useState(false);
  const messageEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const conversationsQuery = useQuery({
    queryKey: ["conversations"],
    queryFn: () =>
      apiRequest<ConversationSummary[]>("/conversations", {}, token),
    enabled: Boolean(token),
  });

  const detailQuery = useQuery({
    queryKey: ["conversation", activeConversationId],
    queryFn: () =>
      apiRequest<ConversationDetail>(
        `/conversations/${activeConversationId}`,
        {},
        token,
      ),
    enabled: Boolean(token && activeConversationId),
  });

  const displayedMessages = useMemo(
    () =>
      localMessagesActive ? messages : (detailQuery.data?.messages ?? []),
    [detailQuery.data?.messages, localMessagesActive, messages],
  );

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [displayedMessages]);

  const evidenceMessage = useMemo(
    () =>
      [...displayedMessages]
        .reverse()
        .find(
          (message) =>
            message.role === "assistant" &&
            (message.citations.length > 0 ||
              message.requires_human ||
              message.ticket_code),
        ) ?? null,
    [displayedMessages],
  );

  const deleteMutation = useMutation({
    mutationFn: (conversationId: string) =>
      apiRequest<void>(
        `/conversations/${conversationId}`,
        { method: "DELETE" },
        token,
      ),
    onSuccess: (_, conversationId) => {
      if (activeConversationId === conversationId) {
        startNewConversation();
      }
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });

  const feedbackMutation = useMutation({
    mutationFn: ({
      messageId,
      rating,
    }: {
      messageId: string;
      rating: FeedbackRating;
    }) =>
      apiRequest("/feedback", {
        method: "POST",
        body: JSON.stringify({ message_id: messageId, rating }),
      }, token),
    onSuccess: (_, variables) => setFeedbackSentId(variables.messageId),
  });

  function startNewConversation() {
    setActiveConversationId(null);
    setMessages([]);
    setLocalMessagesActive(false);
    setComposer("");
    setRequestError("");
    setMobileLedgerOpen(false);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }

  function selectConversation(conversationId: string) {
    if (sending) return;
    setActiveConversationId(conversationId);
    setMessages([]);
    setLocalMessagesActive(false);
    setRequestError("");
    setMobileLedgerOpen(false);
  }

  async function sendMessage(rawMessage: string) {
    const message = rawMessage.trim();
    if (!message || sending || !token) return;

    const pendingId = `assistant-${crypto.randomUUID()}`;
    const existingConversation = activeConversationId;
    let resolvedConversation = existingConversation;
    let resolvedMessageId = pendingId;
    const visibleMessages = localMessagesActive
      ? messages
      : (detailQuery.data?.messages ?? []);
    setMessages([
      ...visibleMessages,
      userMessage(message),
      emptyAssistant(pendingId),
    ]);
    setLocalMessagesActive(true);
    setComposer("");
    setSending(true);
    setRequestError("");

    try {
      await streamChat(
        { conversation_id: existingConversation, message },
        token,
        {
          onMeta: (data) => {
            resolvedConversation = data.conversation_id;
            resolvedMessageId = data.message_id;
            setActiveConversationId(data.conversation_id);
          },
          onDelta: (text) => {
            setMessages((current) =>
              current.map((item) =>
                item.id === pendingId
                  ? { ...item, content: item.content + text }
                  : item,
              ),
            );
          },
          onDone: (data) => {
            setMessages((current) =>
              current.map((item) =>
                item.id === pendingId
                  ? {
                      ...item,
                      id: resolvedMessageId,
                      intent: data.intent,
                      citations: data.citations,
                      requires_human: data.requires_human,
                      human_reason: data.human_reason,
                      suggested_actions: data.suggested_actions,
                      ticket_code: data.ticket_code,
                      warranty_assessment: data.warranty_assessment,
                      pending: false,
                    }
                  : item,
              ),
            );
          },
        },
      );
      if (resolvedConversation) {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["conversations"] }),
          queryClient.invalidateQueries({
            queryKey: ["conversation", resolvedConversation],
          }),
        ]);
      }
    } catch (reason) {
      const messageText =
        reason instanceof ApiError
          ? reason.message
          : "Mất kết nối tới dịch vụ hỗ trợ.";
      setRequestError(messageText);
      setMessages((current) =>
        current.map((item) =>
          item.id === pendingId
            ? {
                ...item,
                content: messageText,
                pending: false,
                failed: true,
              }
            : item,
        ),
      );
    } finally {
      setSending(false);
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      requestAnimationFrame(() => textareaRef.current?.focus());
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void sendMessage(composer);
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      void sendMessage(composer);
    }
  }

  return (
    <main className="chat-workspace">
      <header className="workspace-header">
        <button
          className="icon-button mobile-only"
          type="button"
          aria-label="Mở lịch sử hội thoại"
          onClick={() => setMobileLedgerOpen(true)}
        >
          <Menu size={19} />
        </button>
        <Link to="/chat" className="workspace-brand" onClick={startNewConversation}>
          <span>ĐC</span>
          <strong>Điểm Chạm</strong>
          <small>CSKH có kiểm chứng</small>
        </Link>
        <div className="trust-status">
          <span />
          Nguồn dữ liệu được giới hạn
        </div>
        <div className="header-actions">
          {user?.role === "support" || user?.role === "admin" ? (
            <Link className="quiet-link" to="/admin/operations">
              <Gauge size={17} />
              Vận hành
            </Link>
          ) : null}
          {user?.role === "admin" ? (
            <Link className="quiet-link" to="/admin/knowledge">
              <BookOpenCheck size={17} />
              Kho tri thức
            </Link>
          ) : null}
          <button className="user-chip" type="button" onClick={logout}>
            <CircleUserRound size={19} />
            <span>
              <strong>{user?.full_name}</strong>
              <small>Đăng xuất</small>
            </span>
            <LogOut size={15} />
          </button>
          <button
            className="icon-button mobile-only"
            type="button"
            aria-label="Mở nguồn xác minh"
            onClick={() => setMobileEvidenceOpen(true)}
          >
            <PanelRightOpen size={19} />
          </button>
        </div>
      </header>

      <aside
        className={`conversation-ledger ${mobileLedgerOpen ? "is-open" : ""}`}
        aria-label="Lịch sử hội thoại"
      >
        <div className="panel-heading">
          <div>
            <p className="utility-label">Nhật ký hỗ trợ</p>
            <h2>Cuộc trao đổi</h2>
          </div>
          <button
            className="icon-button mobile-only"
            type="button"
            aria-label="Đóng lịch sử"
            onClick={() => setMobileLedgerOpen(false)}
          >
            <X size={18} />
          </button>
        </div>
        <button
          className="new-conversation"
          type="button"
          onClick={startNewConversation}
        >
          <MessageSquarePlus size={18} />
          Trao đổi mới
        </button>
        <div className="ledger-list">
          {conversationsQuery.isLoading ? (
            <p className="panel-note">Đang đọc nhật ký…</p>
          ) : conversationsQuery.data?.length ? (
            conversationsQuery.data.map((conversation) => (
              <div
                className={`ledger-entry ${
                  activeConversationId === conversation.id ? "is-active" : ""
                }`}
                key={conversation.id}
              >
                <button
                  type="button"
                  onClick={() => selectConversation(conversation.id)}
                  disabled={sending}
                >
                  <History size={15} />
                  <span>
                    <strong>{conversation.title || "Trao đổi chưa đặt tên"}</strong>
                    <small>{formatTime(conversation.updated_at)}</small>
                  </span>
                  <ChevronRight size={14} />
                </button>
                <button
                  className="entry-delete"
                  type="button"
                  aria-label={`Xóa ${conversation.title ?? "cuộc hội thoại"}`}
                  onClick={() => deleteMutation.mutate(conversation.id)}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))
          ) : (
            <div className="empty-ledger">
              <History size={20} />
              <p>Chưa có cuộc trao đổi nào.</p>
              <span>Lịch sử mới sẽ xuất hiện tại đây.</span>
            </div>
          )}
        </div>
        <footer className="ledger-footer">
          <ShieldCheck size={16} />
          <p>
            Danh tính lấy từ phiên đăng nhập. Trợ lý không thể đổi quyền truy cập.
          </p>
        </footer>
      </aside>

      <section className="conversation-stage" aria-label="Nội dung hỗ trợ">
        <div className="stage-heading">
          <div>
            <p className="utility-label">
              {activeConversationId ? "Phiên đang mở" : "Phiên mới"}
            </p>
            <h1>
              {detailQuery.data?.title ||
                (activeConversationId ? "Đang tải cuộc trao đổi…" : "Bạn cần kiểm tra điều gì?")}
            </h1>
          </div>
          <button className="reset-button" type="button" onClick={startNewConversation}>
            <RotateCcw size={15} />
            Bắt đầu lại
          </button>
        </div>

        <div className="message-scroll" aria-live="polite">
          {!displayedMessages.length && !detailQuery.isLoading ? (
            <div className="chat-welcome">
              <div className="welcome-signal" aria-hidden="true">
                <span>01</span>
                <i />
                <span>ĐÃ XÁC MINH</span>
              </div>
              <h2>Hỏi thẳng. Nhận câu trả lời có nguồn.</h2>
              <p>
                Mã đơn, serial và SKU được giữ nguyên. Thông tin riêng chỉ được tra
                cứu trong tài khoản đang đăng nhập.
              </p>
              <div className="suggestion-list">
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => void sendMessage(suggestion)}
                  >
                    <span>{suggestion}</span>
                    <ArrowUp size={16} />
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {detailQuery.isLoading && !displayedMessages.length ? (
            <div className="message-loading">
              <span />
              <span />
              <span />
            </div>
          ) : null}

          <div className="message-list">
            {displayedMessages.map((message, index) =>
              message.role === "user" ? (
                <article className="user-message" key={`${message.id}-${index}`}>
                  <p>{message.content}</p>
                  <time>{formatTime(message.created_at)}</time>
                </article>
              ) : (
                <article
                  className={`assistant-message ${message.failed ? "is-failed" : ""}`}
                  key={`${message.id}-${index}`}
                >
                  <div className="provenance-ribbon" aria-hidden="true">
                    <span />
                    <i />
                  </div>
                  <div className="assistant-meta">
                    <span>CSKH Assistant</span>
                    {message.pending ? (
                      <small>đang kiểm chứng nguồn…</small>
                    ) : (
                      <small>
                        {message.citations.length
                          ? `${message.citations.length} nguồn đã đối chiếu`
                          : "phản hồi từ luồng được kiểm soát"}
                      </small>
                    )}
                  </div>
                  <p className="assistant-content">
                    {message.content}
                    {message.pending && !message.content ? (
                      <span className="typing-cursor" aria-label="Đang trả lời" />
                    ) : null}
                  </p>
                  {message.warranty_assessment ? (
                    <div className="assessment-chip">
                      <ShieldCheck size={14} />
                      {warrantyAssessmentLabel(message.warranty_assessment)}
                    </div>
                  ) : null}
                  {message.requires_human ? (
                    <div className="handoff-notice">
                      <CircleUserRound size={18} />
                      <span>
                        <strong>Cần nhân viên xem xét</strong>
                        {message.ticket_code
                          ? `Ticket ${message.ticket_code} đã được mở.`
                          : "Trợ lý chưa tự đánh dấu vấn đề là đã giải quyết."}
                      </span>
                    </div>
                  ) : null}
                  {message.citations.length ? (
                    <div className="inline-sources">
                      {message.citations.map((citation) => (
                        <span key={citation.label}>
                          <FileText size={13} />
                          {citation.label} · {citation.title}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {message.suggested_actions.length ? (
                    <div className="suggested-actions">
                      {message.suggested_actions.map((action) => (
                        <button
                          type="button"
                          key={action}
                          disabled={sending}
                          onClick={() => void sendMessage(actionMessage(action))}
                        >
                          {actionLabel(action)}
                          <ChevronRight size={15} />
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {!message.pending && !message.failed && !message.id.startsWith("assistant-") ? (
                    <div className="message-feedback" aria-label="Đánh giá câu trả lời">
                      <span>Hữu ích?</span>
                      <button
                        type="button"
                        aria-label="Câu trả lời hữu ích"
                        onClick={() =>
                          feedbackMutation.mutate({
                            messageId: message.id,
                            rating: "positive",
                          })
                        }
                      >
                        <ThumbsUp size={14} />
                      </button>
                      <button
                        type="button"
                        aria-label="Câu trả lời chưa hữu ích"
                        onClick={() =>
                          feedbackMutation.mutate({
                            messageId: message.id,
                            rating: "negative",
                          })
                        }
                      >
                        <ThumbsDown size={14} />
                      </button>
                      {feedbackSentId === message.id ? <em>Đã ghi nhận</em> : null}
                    </div>
                  ) : null}
                </article>
              ),
            )}
          </div>
          <div ref={messageEndRef} />
        </div>

        <div className="composer-zone">
          {requestError ? (
            <p className="composer-error" role="alert">
              {requestError}
            </p>
          ) : null}
          <form className="chat-composer" onSubmit={handleSubmit}>
            <textarea
              ref={textareaRef}
              value={composer}
              onChange={(event) => setComposer(event.target.value.slice(0, 2000))}
              onKeyDown={handleComposerKeyDown}
              placeholder="Nhập câu hỏi, mã đơn, serial hoặc SKU…"
              rows={1}
              disabled={sending}
              aria-label="Tin nhắn hỗ trợ"
            />
            <div>
              <span>{composer.length}/2000</span>
              <button
                type="submit"
                disabled={sending || !composer.trim()}
                aria-label="Gửi tin nhắn"
              >
                <ArrowUp size={19} />
              </button>
            </div>
          </form>
          <p>Enter để gửi · Shift + Enter để xuống dòng</p>
        </div>
      </section>

      <aside
        className={`evidence-rail ${mobileEvidenceOpen ? "is-open" : ""}`}
        aria-label="Nguồn xác minh"
      >
        <div className="panel-heading">
          <div>
            <p className="utility-label">Dải xác minh</p>
            <h2>Nguồn của câu trả lời</h2>
          </div>
          <button
            className="icon-button mobile-only"
            type="button"
            aria-label="Đóng nguồn xác minh"
            onClick={() => setMobileEvidenceOpen(false)}
          >
            <X size={18} />
          </button>
        </div>

        <div className="evidence-timeline">
          <div className="evidence-node is-live">
            <span className="node-marker">
              <CheckCircle2 size={15} />
            </span>
            <div>
              <small>Nguồn trực tiếp</small>
              <strong>Hệ thống hiện tại</strong>
              <p>Giá, tồn kho, đơn hàng và bảo hành chỉ lấy từ dữ liệu live.</p>
            </div>
          </div>

          {evidenceMessage?.citations.map((citation) => (
            <div className="evidence-node" key={citation.label}>
              <span className="node-marker">{citation.label.replace("KB-", "")}</span>
              <div>
                <small>
                  {citation.label} · phiên bản {citation.version}
                </small>
                <strong>{citation.title}</strong>
                <p>{citation.excerpt}</p>
                <dl>
                  <div>
                    <dt>Mục</dt>
                    <dd>{citation.section_path.join(" › ") || "Toàn tài liệu"}</dd>
                  </div>
                  {citation.page ? (
                    <div>
                      <dt>Trang</dt>
                      <dd>{citation.page}</dd>
                    </div>
                  ) : null}
                </dl>
              </div>
            </div>
          ))}

          {evidenceMessage?.requires_human ? (
            <div className="evidence-node is-human">
              <span className="node-marker">
                <CircleUserRound size={15} />
              </span>
              <div>
                <small>Điểm dừng an toàn</small>
                <strong>Chuyển người thật</strong>
                <p>
                  Lý do: {evidenceMessage.human_reason ?? "Cần xác minh thủ công"}.
                </p>
              </div>
            </div>
          ) : null}

          {!evidenceMessage?.citations.length && !evidenceMessage?.requires_human ? (
            <div className="evidence-empty">
              <FileText size={20} />
              <p>Nguồn chính sách sẽ xuất hiện tại đây khi câu trả lời cần trích dẫn.</p>
            </div>
          ) : null}
        </div>

        <footer className="evidence-footer">
          <p className="utility-label">Quy tắc hiển thị</p>
          <p>
            Tài liệu được truy xuất là dữ liệu tham khảo, không phải chỉ dẫn cho trợ lý.
          </p>
        </footer>
      </aside>

      {(mobileLedgerOpen || mobileEvidenceOpen) && (
        <button
          className="mobile-scrim"
          type="button"
          aria-label="Đóng bảng"
          onClick={() => {
            setMobileLedgerOpen(false);
            setMobileEvidenceOpen(false);
          }}
        />
      )}
    </main>
  );
}
