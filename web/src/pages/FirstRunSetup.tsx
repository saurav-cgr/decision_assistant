import { FormEvent, useState } from "react";

import { useAuth } from "../app/AuthContext";
import { useSetup } from "../app/SetupContext";
import type { AuthenticatedUser } from "../api/types";
import "../app/authentication.css";

/**
 * T044 (US5): the first-run "create password" screen.
 *
 * Shown only while the server reports `needs_password_setup` (see `App.tsx`). Two steps on purpose:
 * the recovery code comes back from `POST /setup/password` exactly once, so the screen does not enter
 * the app until the operator has had the chance to save it — the same shape the sign-up flow uses.
 *
 * This screen is a first-run flow, not access control (DB59): the endpoint is unauthenticated because
 * a fresh install has no user to authenticate against, and what bounds the stack is that the app
 * binds to 127.0.0.1 only.
 */
export function FirstRunSetup() {
  const { completeSignUp } = useAuth();
  const { createPassword } = useSetup();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null);
  const [pendingUser, setPendingUser] = useState<AuthenticatedUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (password !== confirmation) {
      setError("The two passwords do not match.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const result = await createPassword(password);
      setRecoveryCode(result.recoveryCode);
      setPendingUser(result.user);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not set the password");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="authentication-page">
      <section className="authentication-card" aria-labelledby="first-run-title">
        <p className="eyebrow">Private decision memory</p>
        <h1 id="first-run-title">Set up this install</h1>
        {recoveryCode === null ? (
          <>
            <p>
              This install has no user yet. Choose the password for the single local account — nothing
              leaves this machine.
            </p>
            <form onSubmit={submit}>
              <label>
                New password
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  minLength={8}
                  autoComplete="new-password"
                  required
                />
              </label>
              <label>
                Repeat password
                <input
                  type="password"
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  minLength={8}
                  autoComplete="new-password"
                  required
                />
              </label>
              {error && (
                <p className="auth-message auth-message--error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" disabled={submitting}>
                {submitting ? "Setting up…" : "Set password and continue"}
              </button>
            </form>
          </>
        ) : (
          <>
            <p>Your password is set. Save this recovery code now — it is shown only once.</p>
            <p className="auth-message" role="status">
              {recoveryCode}
            </p>
            <button type="button" onClick={() => pendingUser && completeSignUp(pendingUser)}>
              I saved my recovery code
            </button>
          </>
        )}
      </section>
    </main>
  );
}
