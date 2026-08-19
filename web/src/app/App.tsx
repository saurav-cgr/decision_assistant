import { BrowserRouter } from "react-router-dom";

import { ApiErrorBoundary } from "../components/ApiError";
import { AppRoutes } from "./router";
import { AuthProvider, useAuth } from "./AuthContext";
import { Authentication } from "../pages/Authentication";

function Application() {
  const { user } = useAuth();
  return user ? <AppRoutes /> : <Authentication />;
}

export function App() {
  return (
    <ApiErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <Application />
        </AuthProvider>
      </BrowserRouter>
    </ApiErrorBoundary>
  );
}
