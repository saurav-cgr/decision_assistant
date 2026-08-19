import { FormEvent, useState } from "react";

import { recoverUsername, resetPassword } from "../api/client";
import { useAuth } from "../app/AuthContext";
import type { AuthenticatedUser } from "../api/types";
import "../app/authentication.css";

type Mode = "login" | "signup" | "recover-username" | "reset-password";

export function Authentication() {
  const { completeSignUp, signIn, signUp } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [pendingUser, setPendingUser] = useState<AuthenticatedUser | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setMessage(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        await signIn(username, password);
      } else if (mode === "signup") {
        const result = await signUp(username, password);
        setPendingUser(result.user);
        setMessage(`Save this recovery code now: ${result.recoveryCode}`);
      } else if (mode === "recover-username") {
        const result = await recoverUsername(recoveryCode);
        setMessage(`Your username is ${result.username}.`);
      } else {
        const result = await resetPassword(username, password, recoveryCode);
        setMessage(`Password reset. Save this new recovery code now: ${result.recovery_code}`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Authentication failed");
    } finally {
      setSubmitting(false);
    }
  };

  const requiresCredentials = mode === "login" || mode === "signup" || mode === "reset-password";
  return (
    <main className="authentication-page">
      <section className="authentication-card" aria-labelledby="authentication-title">
        <p className="eyebrow">Private decision memory</p>
        <h1 id="authentication-title">
          {mode === "login" ? "Sign in" : mode === "signup" ? "Create account" : "Recover access"}
        </h1>
        <p>Accounts and credentials stay in this application’s database.</p>
        <form onSubmit={submit}>
          {requiresCredentials && (
            <label>
              Username
              <input value={username} onChange={(event) => setUsername(event.target.value)} required />
            </label>
          )}
          {requiresCredentials && (
            <label>
              {mode === "reset-password" ? "New password" : "Password"}
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={12} required />
            </label>
          )}
          {(mode === "recover-username" || mode === "reset-password") && (
            <label>
              Recovery code
              <input value={recoveryCode} onChange={(event) => setRecoveryCode(event.target.value)} required />
            </label>
          )}
          {error && <p className="auth-message auth-message--error" role="alert">{error}</p>}
          {message && <p className="auth-message" role="status">{message}</p>}
          <button type="submit" disabled={submitting}>
            {submitting ? "Working…" : mode === "login" ? "Sign in" : mode === "signup" ? "Create account" : "Continue"}
          </button>
          {pendingUser && (
            <button type="button" onClick={() => completeSignUp(pendingUser)}>
              I saved my recovery code
            </button>
          )}
        </form>
        <div className="authentication-links">
          <button type="button" onClick={() => setMode("login")}>Sign in</button>
          <button type="button" onClick={() => setMode("signup")}>Create account</button>
          <button type="button" onClick={() => setMode("recover-username")}>Forgot username</button>
          <button type="button" onClick={() => setMode("reset-password")}>Reset password</button>
        </div>
      </section>
    </main>
  );
}
