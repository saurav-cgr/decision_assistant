import { BrowserRouter } from "react-router-dom";

import { ApiErrorBoundary } from "../components/ApiError";
import { AppRoutes } from "./router";
import { AuthProvider, useAuth } from "./AuthContext";
import { SetupProvider, useSetup } from "./SetupContext";
import { Authentication } from "../pages/Authentication";
import { FirstRunSetup } from "../pages/FirstRunSetup";

function Application() {
  const { user } = useAuth();
  const { status, loading } = useSetup();

  if (user) {
    return <AppRoutes />;
  }
  // T044: wait for the status answer before choosing a screen. Rendering the sign-in form first and
  // swapping it for the first-run screen a moment later would ask a fresh install's operator to sign
  // in to an account that cannot exist yet. A failed probe (`status === null` after loading) falls
  // through to the sign-in form on purpose — see SetupContext.
  if (loading) {
    return (
      <main className="authentication-page">
        <section className="authentication-card" aria-live="polite">
          <p className="eyebrow">Private decision memory</p>
          <p>Checking this install…</p>
        </section>
      </main>
    );
  }
  return status?.needs_password_setup ? <FirstRunSetup /> : <Authentication />;
}

export function App() {
  return (
    <ApiErrorBoundary>
      <BrowserRouter>
        <SetupProvider>
          <AuthProvider>
            <Application />
          </AuthProvider>
        </SetupProvider>
      </BrowserRouter>
    </ApiErrorBoundary>
  );
}
