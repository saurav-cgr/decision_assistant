import { createContext, useContext, useEffect, useMemo, useState } from "react";

import {
  login as loginRequest,
  logout as logoutRequest,
  setAccessToken,
  setUnauthorizedHandler,
  signUp as signUpRequest,
} from "../api/client";
import type { AuthenticatedUser } from "../api/types";

type AuthContextValue = {
  user: AuthenticatedUser | null;
  signIn: (username: string, password: string) => Promise<void>;
  signUp: (
    username: string,
    password: string,
  ) => Promise<{ recoveryCode: string; user: AuthenticatedUser }>;
  completeSignUp: (user: AuthenticatedUser) => void;
  clearSession: () => void;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAccessToken(null);
      setUser(null);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      async signIn(username, password) {
        const response = await loginRequest(username, password);
        setAccessToken(response.access_token);
        setUser(response.user);
      },
      async signUp(username, password) {
        const response = await signUpRequest(username, password);
        setAccessToken(response.access_token);
        return { recoveryCode: response.recovery_code ?? "", user: response.user };
      },
      completeSignUp(user) {
        setUser(user);
      },
      clearSession() {
        setAccessToken(null);
        setUser(null);
      },
      async signOut() {
        try {
          await logoutRequest();
        } finally {
          setAccessToken(null);
          setUser(null);
        }
      },
    }),
    [user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return value;
}
