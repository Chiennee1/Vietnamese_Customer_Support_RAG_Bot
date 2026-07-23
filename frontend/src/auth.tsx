import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { AuthContext } from "./auth-context";
import { apiRequest } from "./lib/api";
import type { TokenResponse, User } from "./types";

const TOKEN_KEY = "support_access_token";
const USER_KEY = "support_user";

function storedUser(): User | null {
  const value = sessionStorage.getItem(USER_KEY);
  if (!value) return null;
  try {
    return JSON.parse(value) as User;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() =>
    sessionStorage.getItem(TOKEN_KEY),
  );
  const [user, setUser] = useState<User | null>(storedUser);
  const [ready, setReady] = useState(
    () => !sessionStorage.getItem(TOKEN_KEY),
  );

  const logout = useCallback(() => {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
    setReady(true);
  }, []);

  useEffect(() => {
    const handleExpiry = () => logout();
    window.addEventListener("support:auth-expired", handleExpiry);
    return () => window.removeEventListener("support:auth-expired", handleExpiry);
  }, [logout]);

  useEffect(() => {
    if (!token) return;
    apiRequest<User>("/auth/me", {}, token)
      .then((currentUser) => {
        setUser(currentUser);
        sessionStorage.setItem(USER_KEY, JSON.stringify(currentUser));
      })
      .catch(() => logout())
      .finally(() => setReady(true));
  }, [logout, token]);

  const login = useCallback(async (email: string, password: string) => {
    const response = await apiRequest<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    sessionStorage.setItem(TOKEN_KEY, response.access_token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(response.user));
    setToken(response.access_token);
    setUser(response.user);
    setReady(true);
    return response.user;
  }, []);

  const value = useMemo(
    () => ({ token, user, ready, login, logout }),
    [token, user, ready, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
