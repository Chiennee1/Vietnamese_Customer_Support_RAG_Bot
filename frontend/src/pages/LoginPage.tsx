import { useState, type FormEvent } from "react";
import { ArrowRight, Check, Database, FileCheck2, ShieldCheck } from "lucide-react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth-context";
import { ApiError } from "../lib/api";

const DEMO_PASSWORD = "Demo-customer-2026";

export function LoginPage() {
  const { token, user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("customer0006@example.test");
  const [password, setPassword] = useState(DEMO_PASSWORD);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (token && user) {
    return <Navigate to={user.role === "admin" ? "/admin/knowledge" : "/chat"} replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const signedInUser = await login(email, password);
      const requestedPath = (location.state as { from?: string } | null)?.from;
      navigate(
        requestedPath ??
          (signedInUser.role === "admin" ? "/admin/knowledge" : "/chat"),
        { replace: true },
      );
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Không thể kết nối tới dịch vụ đăng nhập.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  function fillDemo(kind: "customer" | "admin") {
    setEmail(
      kind === "admin"
        ? "customer0000@example.test"
        : "customer0006@example.test",
    );
    setPassword(DEMO_PASSWORD);
    setError("");
  }

  return (
    <main className="login-page">
      <section className="login-story" aria-labelledby="login-title">
        <div className="brand-mark" aria-hidden="true">
          <span>ĐC</span>
          <i />
        </div>
        <p className="utility-label">Điểm Chạm · CSKH có kiểm chứng</p>
        <h1 id="login-title">
          Mỗi câu trả lời,
          <span> một dấu vết rõ ràng.</span>
        </h1>
        <p className="login-intro">
          Tra cứu đơn hàng, bảo hành và chính sách bằng đúng nguồn được phép —
          dữ liệu hiện tại từ hệ thống, điều kiện từ tài liệu đã công bố.
        </p>
        <div className="trust-ledger" aria-label="Nguyên tắc vận hành">
          <div>
            <Database size={18} />
            <span>
              <strong>Dữ liệu trực tiếp</strong>
              Giá, tồn kho và trạng thái của riêng bạn
            </span>
            <Check size={16} />
          </div>
          <div>
            <FileCheck2 size={18} />
            <span>
              <strong>Chính sách đã công bố</strong>
              Trích dẫn theo tài liệu, phiên bản và mục
            </span>
            <Check size={16} />
          </div>
          <div>
            <ShieldCheck size={18} />
            <span>
              <strong>Quyền riêng tư mặc định</strong>
              Không truy cập chéo dữ liệu khách hàng
            </span>
            <Check size={16} />
          </div>
        </div>
      </section>

      <section className="login-panel" aria-label="Đăng nhập">
        <div className="login-card">
          <header>
            <p className="utility-label">Phiên hỗ trợ bảo mật</p>
            <h2>Đăng nhập để bắt đầu</h2>
            <p>Dùng tài khoản synthetic bên dưới cho bản demo portfolio.</p>
          </header>

          <div className="demo-switch" aria-label="Chọn tài khoản demo">
            <button type="button" onClick={() => fillDemo("customer")}>
              Khách hàng
            </button>
            <button type="button" onClick={() => fillDemo("admin")}>
              Quản trị tri thức
            </button>
          </div>

          <form onSubmit={handleSubmit}>
            <label>
              Email
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>
            <label>
              Mật khẩu
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>
            {error ? (
              <p className="form-error" role="alert">
                {error}
              </p>
            ) : null}
            <button className="primary-action" type="submit" disabled={submitting}>
              <span>{submitting ? "Đang xác minh…" : "Vào phiên hỗ trợ"}</span>
              <ArrowRight size={18} />
            </button>
          </form>

          <footer>
            <span className="status-dot" />
            Chỉ dùng dữ liệu synthetic — không chứa thông tin khách thật
          </footer>
        </div>
      </section>
    </main>
  );
}
