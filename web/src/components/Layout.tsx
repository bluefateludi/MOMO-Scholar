import { NavLink, Outlet } from "react-router-dom";
import { isMockMode } from "../api";

export function Layout() {
  return <div className="app-shell">
    <a className="skip-link" href="#main">Skip to content</a>
    {isMockMode && <div className="fixture-banner" role="status">Synthetic fixture mode · simulated lifecycle · no provider, network, or Docker calls</div>}
    <header className="masthead">
      <NavLink className="wordmark" to="/" aria-label="MOMO TechScout home"><span>MOMO</span><strong>TechScout</strong></NavLink>
      <div className="masthead-note">Evidence &amp; verification desk <i aria-hidden="true">W2</i></div>
    </header>
    <main id="main"><Outlet /></main>
    <footer><span>MOMO TechScout / local Wave 2 integration</span><span>Evidence before recommendation.</span></footer>
  </div>;
}
