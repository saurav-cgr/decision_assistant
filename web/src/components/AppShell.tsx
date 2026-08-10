import { NavLink, Outlet } from "react-router-dom";

const navigation = [
  { label: "Workspace", to: "/", end: true },
  { label: "Ask", to: "/ask" },
  { label: "Timeline", to: "/timeline" },
  { label: "Evaluation", to: "/evaluation" },
] as const;

export function AppShell() {
  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="Decision Assistant home">
          <span className="brand__mark" aria-hidden="true">
            DA
          </span>
          <span>
            <strong>Decision Assistant</strong>
            <small>Project memory, with evidence</small>
          </span>
        </a>
        <div className="local-status" aria-label="Environment status">
          <span aria-hidden="true" />
          Local workspace
        </div>
      </header>

      <nav className="primary-nav" aria-label="Primary navigation">
        {navigation.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={"end" in item ? item.end : false}
            className={({ isActive }) =>
              isActive ? "primary-nav__link is-active" : "primary-nav__link"
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main className="main-content">
        <Outlet />
      </main>

      <footer className="site-footer">
        <span>Local-first decision intelligence</span>
        <span>Sources remain authoritative</span>
      </footer>
    </div>
  );
}
