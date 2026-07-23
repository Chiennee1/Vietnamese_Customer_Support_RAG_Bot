import { createContext, useContext } from "react";

import type { User } from "./types";

export interface AuthContextValue {
  token: string | null;
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth phải được dùng bên trong AuthProvider");
  }
  return value;
}
