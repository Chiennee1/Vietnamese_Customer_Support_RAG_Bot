import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BookOpenCheck,
  LogOut,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  TicketCheck,
} from "lucide-react";
import { Link } from "react-router-dom";

import { useAuth } from "../auth-context";
import { apiRequest } from "../lib/api";
import type {
  ControlledReviewMessage,
  EscalationReview,
  OperationsMetrics,
  TicketReview,
} from "../types";

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function statusLabel(value: TicketReview["status"]): string {
  return {
    open: "Mới",
    in_review: "Đang xem xét",
    resolved: "Đã xử lý",
  }[value];
}

export function AdminOperationsPage() {
  const { token, user, logout } = useAuth();
  const [selectedConversation, setSelectedConversation] = useState<
    string | null
  >(null);
  const metrics = useQuery({
    queryKey: ["operations-metrics"],
    queryFn: () => apiRequest<OperationsMetrics>("/admin/metrics", {}, token),
    enabled: Boolean(token),
    refetchInterval: 15_000,
  });
  const escalations = useQuery({
    queryKey: ["review-escalations"],
    queryFn: () =>
      apiRequest<EscalationReview[]>(
        "/admin/review/escalations",
        {},
        token,
      ),
    enabled: Boolean(token),
    refetchInterval: 15_000,
  });
  const tickets = useQuery({
    queryKey: ["review-tickets"],
    queryFn: () =>
      apiRequest<TicketReview[]>("/admin/review/tickets", {}, token),
    enabled: Boolean(token),
    refetchInterval: 15_000,
  });
  const transcript = useQuery({
    queryKey: ["review-transcript", selectedConversation],
    queryFn: () =>
      apiRequest<ControlledReviewMessage[]>(
        `/admin/review/escalations/${selectedConversation}/messages`,
        {},
        token,
      ),
    enabled: Boolean(token && selectedConversation),
  });

  const refresh = () => {
    void metrics.refetch();
    void escalations.refetch();
    void tickets.refetch();
  };
  const chatCount = metrics.data?.chat.latency.count ?? 0;
  const noEvidence = metrics.data?.rag.no_result ?? 0;

  return (
    <main className="admin-page">
      <header className="admin-header">
        <Link to="/chat" className="workspace-brand">
          <span>ĐC</span>
          <strong>Điểm Chạm</strong>
          <small>Bàn điều phối hỗ trợ</small>
        </Link>
        <nav>
          {user?.role === "admin" ? (
            <Link className="quiet-link" to="/admin/knowledge">
              <BookOpenCheck size={17} />
              Kho tri thức
            </Link>
          ) : null}
          <Link className="quiet-link" to="/chat">
            <ArrowLeft size={17} />
            Về hội thoại
          </Link>
          <button className="user-chip" type="button" onClick={logout}>
            <ShieldCheck size={18} />
            <span>
              <strong>{user?.full_name}</strong>
              <small>Nhân viên hỗ trợ</small>
            </span>
            <LogOut size={15} />
          </button>
        </nav>
      </header>

      <section className="admin-hero operations-hero">
        <div>
          <p className="utility-label">Hàng đợi chỉ đọc · giới hạn 50 mục</p>
          <h1>Việc cần người thật, hiện rõ trước tiên.</h1>
          <p>
            Màn hình này chỉ hiển thị dữ liệu cần để điều phối. Trợ lý không tự
            đóng khiếu nại hay phê duyệt hoàn tiền, đổi máy hoặc bảo hành.
          </p>
        </div>
        <div className="knowledge-stats" aria-label="Chỉ số vận hành">
          <div>
            <strong>{chatCount}</strong>
            <span>Lượt chat đo được</span>
          </div>
          <div>
            <strong>{metrics.data?.chat.latency.p95_ms ?? 0}</strong>
            <span>P95 · mili giây</span>
          </div>
          <div>
            <strong>{metrics.data?.chat.tickets_created ?? 0}</strong>
            <span>Ticket đã tạo</span>
          </div>
          <div className={noEvidence > 0 ? "has-alert" : ""}>
            <strong>{noEvidence}</strong>
            <span>Thiếu evidence</span>
          </div>
        </div>
      </section>

      <section className="operations-toolbar">
        <div>
          <Activity size={17} />
          Tự làm mới mỗi 15 giây
        </div>
        <button type="button" onClick={refresh}>
          <RefreshCw size={15} />
          Làm mới
        </button>
      </section>

      <section className="operations-grid">
        <article className="review-board">
          <header>
            <div>
              <p className="utility-label">Ưu tiên xem xét</p>
              <h2>Hội thoại chuyển người thật</h2>
            </div>
            <AlertTriangle size={20} />
          </header>
          <div className="review-list">
            {escalations.isLoading ? (
              <p className="panel-note">Đang đọc hàng đợi…</p>
            ) : escalations.data?.length ? (
              escalations.data.map((item) => (
                <div className="review-row" key={`${item.conversation_id}-${item.raised_at}`}>
                  <div>
                    <strong>{item.title || "Hội thoại chưa đặt tên"}</strong>
                    <span>{item.human_reason || "Cần xem xét thủ công"}</span>
                    <button
                      className="transcript-button"
                      type="button"
                      onClick={() =>
                        setSelectedConversation(item.conversation_id)
                      }
                    >
                      <MessageSquareText size={13} />
                      Xem nhật ký được kiểm soát
                    </button>
                  </div>
                  <div className="review-meta">
                    <code>{item.ticket_code || "CHƯA CÓ TICKET"}</code>
                    <time>{formatDate(item.raised_at)}</time>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-review">Chưa có hội thoại cần chuyển.</p>
            )}
          </div>
          {selectedConversation ? (
            <section className="controlled-transcript">
              <header>
                <strong>Nhật ký hội thoại</strong>
                <button
                  type="button"
                  onClick={() => setSelectedConversation(null)}
                >
                  Đóng
                </button>
              </header>
              {transcript.isLoading ? (
                <p>Đang tải nội dung…</p>
              ) : transcript.data?.map((message, index) => (
                <div
                  className={`transcript-message is-${message.role}`}
                  key={`${message.created_at}-${index}`}
                >
                  <span>
                    {message.role === "user" ? "Khách hàng" : "CSKH Assistant"}
                  </span>
                  <p>{message.content}</p>
                  <time>{formatDate(message.created_at)}</time>
                </div>
              ))}
            </section>
          ) : null}
        </article>

        <article className="review-board">
          <header>
            <div>
              <p className="utility-label">Theo dõi nghiệp vụ</p>
              <h2>Ticket hỗ trợ gần nhất</h2>
            </div>
            <TicketCheck size={20} />
          </header>
          <div className="review-list">
            {tickets.isLoading ? (
              <p className="panel-note">Đang đọc ticket…</p>
            ) : tickets.data?.length ? (
              tickets.data.map((item) => (
                <div className="review-row ticket-row" key={item.ticket_code}>
                  <div>
                    <div className="ticket-heading">
                      <code>{item.ticket_code}</code>
                      <span className={`severity-${item.severity}`}>
                        {item.severity}
                      </span>
                    </div>
                    <strong>{item.subject}</strong>
                    <p>{item.summary}</p>
                  </div>
                  <div className="review-meta">
                    <span>{statusLabel(item.status)}</span>
                    <time>{formatDate(item.created_at)}</time>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-review">Chưa có ticket hỗ trợ.</p>
            )}
          </div>
        </article>
      </section>
    </main>
  );
}
