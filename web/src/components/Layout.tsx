import { NavLink, Outlet } from "react-router-dom";
import { isMockMode } from "../api";

export function Layout() {
  return <div className="app-shell">
    <a className="skip-link" href="#main">Skip to content</a>
    {isMockMode && <div className="fixture-banner" role="status">Contract fixture mode · simulated lifecycle · no provider calls</div>}
    <header className="masthead">
      <NavLink className="wordmark" to="/" aria-label="MOMO Scholar home"><span>MOMO</span><strong>Scholar</strong></NavLink>
      <div className="masthead-note">Local research desk <i aria-hidden="true">№ 04</i></div>
    </header>
    <main id="main"><Outlet /></main>
    <footer><span>MOMO Scholar / local-only Web MVP</span><span>Evidence before assertion.</span></footer>
  </div>;
}
