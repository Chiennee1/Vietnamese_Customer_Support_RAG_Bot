import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./auth-context";
import { AdminKnowledgePage } from "./pages/AdminKnowledgePage";
import { AdminOperationsPage } from "./pages/AdminOperationsPage";
import { ChatPage } from "./pages/ChatPage";
import { LoginPage } from "./pages/LoginPage";
import type { UserRole } from "./types";

function ProtectedRoute({
  children,
  role,
}: {
  children: React.ReactNode;
  role?: UserRole | UserRole[];
}) {
  const { token, user, ready } = useAuth();
  const location = useLocation();

  if (!ready) {
    return (
      <main className="app-loading">
        <div className="loading-signal" />
        <p>Đang xác minh phiên hỗ trợ…</p>
      </main>
    );
  }
  if (!token || !user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  if (
    role &&
    !(Array.isArray(role) ? role.includes(user.role) : user.role === role)
  ) {
    return <Navigate to="/chat" replace />;
  }
  return children;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/chat"
        element={
          <ProtectedRoute>
            <ChatPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/knowledge"
        element={
          <ProtectedRoute role="admin">
            <AdminKnowledgePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/operations"
        element={
          <ProtectedRoute role={["support", "admin"]}>
            <AdminOperationsPage />
          </ProtectedRoute>
        }
      />
      <Route path="/" element={<Navigate to="/chat" replace />} />
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  );
}
