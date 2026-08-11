import { Route, Routes } from "react-router-dom";

import { AppShell } from "../components/AppShell";
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
        <Route
          path="ask"
          element={
            <PlaceholderPage
              eyebrow="Evidence-backed answers"
              title="Ask"
              description="Ask what changed, why it changed, and who owned the call."
            />
          }
        />
        <Route
          path="timeline"
          element={
            <PlaceholderPage
              eyebrow="Decision history"
              title="Timeline"
              description="Follow proposals, revisions, and superseded decisions in order."
            />
          }
        />
        <Route
          path="decisions/:id"
          element={
            <PlaceholderPage
              eyebrow="Structured record"
              title="Decision detail"
              description="Review fields, corrections, relationships, and exact evidence."
            />
          }
        />
        <Route
          path="evaluation"
          element={
            <PlaceholderPage
              eyebrow="Quality lab"
              title="Evaluation"
              description="Compare retrieval strategies and inspect answer-quality metrics."
            />
          }
        />
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
