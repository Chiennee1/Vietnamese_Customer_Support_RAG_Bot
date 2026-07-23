import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArrowLeft,
  BookOpenCheck,
  CheckCircle2,
  FileText,
  LogOut,
  RefreshCw,
  Send,
  ShieldCheck,
  UploadCloud,
} from "lucide-react";
import { Link } from "react-router-dom";

import { useAuth } from "../auth-context";
import { ApiError, apiRequest } from "../lib/api";
import type { DocumentStatus, KnowledgeDocument } from "../types";

const STATUS_LABEL: Record<DocumentStatus, string> = {
  uploaded: "Đã nhận",
  processing: "Đang xử lý",
  ready: "Sẵn sàng duyệt",
  published: "Đã công bố",
  failed: "Lỗi xử lý",
  archived: "Đã lưu trữ",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function AdminKnowledgePage() {
  const { token, user, logout } = useAuth();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [version, setVersion] = useState("1.0");
  const [category, setCategory] = useState("faq");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [effectiveTo, setEffectiveTo] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [formError, setFormError] = useState("");
  const [formSuccess, setFormSuccess] = useState("");

  const documentsQuery = useQuery({
    queryKey: ["knowledge-documents"],
    queryFn: () =>
      apiRequest<KnowledgeDocument[]>("/documents", {}, token),
    enabled: Boolean(token),
    refetchInterval: (query) => {
      const documents = query.state.data;
      return documents?.some((document) =>
        ["uploaded", "processing"].includes(document.status),
      )
        ? 3000
        : false;
    },
  });

  const stats = useMemo(() => {
    const documents = documentsQuery.data ?? [];
    return {
      total: documents.length,
      published: documents.filter((item) => item.status === "published").length,
      review: documents.filter((item) => item.status === "ready").length,
      failed: documents.filter((item) => item.status === "failed").length,
    };
  }, [documentsQuery.data]);

  const uploadMutation = useMutation({
    mutationFn: (form: FormData) =>
      apiRequest<KnowledgeDocument>(
        "/documents",
        { method: "POST", body: form },
        token,
      ),
    onSuccess: (createdDocument) => {
      setFormSuccess(`Đã nhận ${createdDocument.source_filename} để xử lý.`);
      setTitle("");
      setVersion("1.0");
      setEffectiveFrom("");
      setEffectiveTo("");
      setFile(null);
      const input = window.document.querySelector<HTMLInputElement>("#knowledge-file");
      if (input) input.value = "";
      void queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] });
    },
    onError: (reason) => {
      setFormError(
        reason instanceof ApiError
          ? reason.message
          : "Không thể tải tài liệu lên.",
      );
    },
  });

  const lifecycleMutation = useMutation({
    mutationFn: ({
      documentId,
      action,
    }: {
      documentId: string;
      action: "publish" | "archive" | "retry";
    }) =>
      apiRequest<KnowledgeDocument>(
        `/documents/${documentId}/${action}`,
        { method: "POST" },
        token,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledge-documents"] });
    },
  });

  function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    setFormSuccess("");
    if (!file) {
      setFormError("Chọn một tệp PDF, Markdown hoặc TXT.");
      return;
    }
    const form = new FormData();
    form.set("title", title.trim());
    form.set("version", version.trim());
    form.set("category", category);
    form.set("file", file);
    if (effectiveFrom) form.set("effective_from", new Date(effectiveFrom).toISOString());
    if (effectiveTo) form.set("effective_to", new Date(effectiveTo).toISOString());
    uploadMutation.mutate(form);
  }

  return (
    <main className="admin-page">
      <header className="admin-header">
        <Link to="/chat" className="workspace-brand">
          <span>ĐC</span>
          <strong>Điểm Chạm</strong>
          <small>Quản trị tri thức</small>
        </Link>
        <nav>
          <Link className="quiet-link" to="/chat">
            <ArrowLeft size={17} />
            Về hội thoại
          </Link>
          <button className="user-chip" type="button" onClick={logout}>
            <ShieldCheck size={18} />
            <span>
              <strong>{user?.full_name}</strong>
              <small>Quản trị viên</small>
            </span>
            <LogOut size={15} />
          </button>
        </nav>
      </header>

      <section className="admin-hero">
        <div>
          <p className="utility-label">Nguồn chính sách được phê duyệt</p>
          <h1>Kho tri thức có vòng đời rõ ràng.</h1>
          <p>
            Tài liệu chỉ được truy xuất sau khi xử lý xong và quản trị viên chủ
            động công bố phiên bản hiệu lực.
          </p>
        </div>
        <div className="knowledge-stats" aria-label="Thống kê tài liệu">
          <div>
            <strong>{String(stats.total).padStart(2, "0")}</strong>
            <span>Tổng tài liệu</span>
          </div>
          <div>
            <strong>{String(stats.published).padStart(2, "0")}</strong>
            <span>Đang công bố</span>
          </div>
          <div>
            <strong>{String(stats.review).padStart(2, "0")}</strong>
            <span>Chờ duyệt</span>
          </div>
          <div className={stats.failed ? "has-alert" : ""}>
            <strong>{String(stats.failed).padStart(2, "0")}</strong>
            <span>Cần xử lý</span>
          </div>
        </div>
      </section>

      <div className="admin-grid">
        <section className="upload-sheet" aria-labelledby="upload-title">
          <header>
            <span className="sheet-number">01</span>
            <div>
              <p className="utility-label">Nạp nguồn mới</p>
              <h2 id="upload-title">Thông tin phiên bản</h2>
            </div>
          </header>
          <form onSubmit={handleUpload}>
            <label>
              Tên tài liệu
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Chính sách bảo hành điện thoại"
                minLength={2}
                maxLength={240}
                required
              />
            </label>
            <div className="form-row">
              <label>
                Phiên bản
                <input
                  value={version}
                  onChange={(event) => setVersion(event.target.value)}
                  maxLength={40}
                  required
                />
              </label>
              <label>
                Nhóm nội dung
                <select
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  <option value="faq">FAQ</option>
                  <option value="warranty">Bảo hành</option>
                  <option value="returns">Đổi trả</option>
                  <option value="shipping">Giao hàng</option>
                  <option value="payment">Thanh toán</option>
                </select>
              </label>
            </div>
            <div className="form-row">
              <label>
                Hiệu lực từ
                <input
                  type="datetime-local"
                  value={effectiveFrom}
                  onChange={(event) => setEffectiveFrom(event.target.value)}
                />
              </label>
              <label>
                Hiệu lực đến
                <input
                  type="datetime-local"
                  value={effectiveTo}
                  onChange={(event) => setEffectiveTo(event.target.value)}
                />
              </label>
            </div>
            <label className="file-drop" htmlFor="knowledge-file">
              <UploadCloud size={25} />
              <span>
                <strong>{file?.name ?? "Chọn tài liệu để tải lên"}</strong>
                PDF, Markdown hoặc TXT · tối đa 20 MB
              </span>
              <input
                id="knowledge-file"
                type="file"
                accept=".pdf,.md,.txt,application/pdf,text/markdown,text/plain"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>
            {formError ? (
              <p className="form-error" role="alert">
                {formError}
              </p>
            ) : null}
            {formSuccess ? (
              <p className="form-success" role="status">
                <CheckCircle2 size={15} />
                {formSuccess}
              </p>
            ) : null}
            <button
              className="primary-action"
              type="submit"
              disabled={uploadMutation.isPending}
            >
              <span>
                {uploadMutation.isPending ? "Đang tải lên…" : "Tải lên và xử lý"}
              </span>
              <UploadCloud size={18} />
            </button>
          </form>
        </section>

        <section className="document-register" aria-labelledby="register-title">
          <header>
            <div>
              <p className="utility-label">Sổ đăng ký</p>
              <h2 id="register-title">Phiên bản tài liệu</h2>
            </div>
            <button
              className="icon-button"
              type="button"
              aria-label="Tải lại danh sách"
              onClick={() => void documentsQuery.refetch()}
            >
              <RefreshCw size={17} />
            </button>
          </header>

          {documentsQuery.isLoading ? (
            <p className="panel-note">Đang đọc kho tri thức…</p>
          ) : documentsQuery.isError ? (
            <p className="form-error">Không thể tải danh sách tài liệu.</p>
          ) : documentsQuery.data?.length ? (
            <div className="document-list">
              {documentsQuery.data.map((item) => (
                <article className="document-row" key={item.id}>
                  <div className="document-icon">
                    <FileText size={20} />
                  </div>
                  <div className="document-main">
                    <div>
                      <h3>{item.title}</h3>
                      <span
                        className={`document-status status-${item.status}`}
                      >
                        {STATUS_LABEL[item.status]}
                      </span>
                    </div>
                    <p>
                      {item.source_filename} · {item.category} · v{item.version}
                    </p>
                    <dl>
                      <div>
                        <dt>Công bố</dt>
                        <dd>{formatDate(item.published_at)}</dd>
                      </div>
                      <div>
                        <dt>Hiệu lực từ</dt>
                        <dd>{formatDate(item.effective_from)}</dd>
                      </div>
                      <div>
                        <dt>Checksum</dt>
                        <dd>{item.checksum.slice(0, 12)}…</dd>
                      </div>
                    </dl>
                    {item.failure_reason ? (
                      <p className="document-failure">{item.failure_reason}</p>
                    ) : null}
                  </div>
                  <div className="document-actions">
                    {item.status === "ready" ? (
                      <button
                        type="button"
                        onClick={() =>
                          lifecycleMutation.mutate({
                            documentId: item.id,
                            action: "publish",
                          })
                        }
                      >
                        <Send size={14} />
                        Công bố
                      </button>
                    ) : null}
                    {item.status === "published" ? (
                      <button
                        type="button"
                        onClick={() =>
                          lifecycleMutation.mutate({
                            documentId: item.id,
                            action: "archive",
                          })
                        }
                      >
                        <Archive size={14} />
                        Lưu trữ
                      </button>
                    ) : null}
                    {item.status === "failed" ? (
                      <button
                        type="button"
                        onClick={() =>
                          lifecycleMutation.mutate({
                            documentId: item.id,
                            action: "retry",
                          })
                        }
                      >
                        <RefreshCw size={14} />
                        Xử lý lại
                      </button>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="document-empty">
              <BookOpenCheck size={25} />
              <h3>Kho tri thức đang trống</h3>
              <p>Tải tài liệu đầu tiên để bắt đầu quy trình xét duyệt.</p>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
