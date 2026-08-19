import { Route, Routes } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import { Ask } from "../pages/Ask";
import { Account } from "../pages/Account";
import { DecisionDetail } from "../pages/DecisionDetail";
import { Evaluation } from "../pages/Evaluation";
import { Timeline } from "../pages/Timeline";
import { Workspace } from "../pages/Workspace";

type PlaceholderPageProps = {
  eyebrow: string;
  title: string;
  description: string;
};

function PlaceholderPage({ eyebrow, title, description }: PlaceholderPageProps) {
  return (
    <section className="page-intro" aria-labelledby="page-title">
      <p className="eyebrow">{eyebrow}</p>
      <h1 id="page-title">{title}</h1>
      <p className="page-description">{description}</p>
      <div className="empty-panel">
        <span className="empty-panel__marker" aria-hidden="true" />
        <div>
          <h2>Ready for project evidence</h2>
          <p>
            This workspace runs locally. Uploaded evidence and model requests stay
            inside your configured environment.
          </p>
        </div>
      </div>
    </section>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Workspace />} />
        <Route path="ask" element={<Ask />} />
        <Route path="timeline" element={<Timeline />} />
        <Route path="decisions/:id" element={<DecisionDetail />} />
        <Route path="evaluation" element={<Evaluation />} />
        <Route path="account" element={<Account />} />
        <Route
          path="*"
          element={
            <PlaceholderPage
              eyebrow="Not found"
              title="Page unavailable"
              description="Use the primary navigation to return to a product workspace."
            />
          }
        />
      </Route>
    </Routes>
  );
}
