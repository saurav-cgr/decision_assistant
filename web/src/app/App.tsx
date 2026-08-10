import { BrowserRouter } from "react-router-dom";

import { ApiErrorBoundary } from "../components/ApiError";
import { AppRoutes } from "./router";

export function App() {
  return (
    <ApiErrorBoundary>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </ApiErrorBoundary>
  );
}
