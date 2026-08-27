import { FormEvent, useState } from "react";

import {
  changePassword,
  changeUsername,
  rotateRecoveryCode,
} from "../api/client";
import { useAuth } from "../app/AuthContext";
import "../app/authentication.css";

export function Account() {
  const { clearSession, user } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [username, setUsername] = useState(user?.username ?? "");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (action: () => Promise<void>, success: string) => {
    setError(null);
    setMessage(null);
    try {
      await action();
      setMessage(success);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Account update failed");
    }
  };

  const changePasswordSubmit = (event: FormEvent) => {
    event.preventDefault();
    void submit(async () => {
      await changePassword(currentPassword, newPassword);
      clearSession();
    }, "Password changed. Sign in again to continue.");
  };
  const changeUsernameSubmit = (event: FormEvent) => {
    event.preventDefault();
    void submit(async () => {
      await changeUsername(currentPassword, username);
      clearSession();
    }, "Username changed. Sign in again to continue.");
  };
  const rotateCodeSubmit = (event: FormEvent) => {
    event.preventDefault();
    void (async () => {
      setError(null);
      try {
        const result = await rotateRecoveryCode(currentPassword);
        setMessage(`Save this new recovery code now: ${result.recovery_code}`);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Account update failed");
      }
    })();
  };

  return (
    <section className="account-page" aria-labelledby="account-title">
      <p className="eyebrow">Account</p>
      <h1 id="account-title">Security settings</h1>
      {error && <p className="auth-message auth-message--error" role="alert">{error}</p>}
      {message && <p className="auth-message" role="status">{message}</p>}
      <div className="account-forms">
        <form onSubmit={changeUsernameSubmit}>
          <h2>Change username</h2>
          <label htmlFor="new-username">New username</label>
          <input id="new-username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
          <label htmlFor="username-current-password">Current password</label>
          <input id="username-current-password" type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} autoComplete="current-password" required />
          <button>Update username</button>
        </form>
        <form onSubmit={changePasswordSubmit}>
          <h2>Change password</h2>
          <label htmlFor="password-current-password">Current password</label>
          <input id="password-current-password" type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} autoComplete="current-password" required />
          <label htmlFor="new-password">New password</label>
          <input id="new-password" type="password" minLength={8} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" required />
          <button>Update password</button>
        </form>
        <form onSubmit={rotateCodeSubmit}>
          <h2>Replace recovery code</h2>
          <label htmlFor="recovery-current-password">Current password</label>
          <input id="recovery-current-password" type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} autoComplete="current-password" required />
          <button>Generate recovery code</button>
        </form>
      </div>
    </section>
  );
}
