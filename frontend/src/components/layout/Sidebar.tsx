import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  FileText,
  GitBranch
} from "lucide-react";

// Links to the main pages.
function Sidebar() {
  return (
    <aside className="sidebar">

      <div className="sidebar-section">
        <p className="sidebar-heading">WORKSPACE</p>

        <NavLink to="/" className="sidebar-link">
          <LayoutDashboard size={19} />
          <span>Dashboard</span>
        </NavLink>

        <NavLink to="/results" className="sidebar-link">
          <FileText size={19} />
          <span>Generated Tests</span>
        </NavLink>

        <NavLink to="/traceability" className="sidebar-link">
          <GitBranch size={19} />
          <span>Traceability</span>
        </NavLink>
      </div>

    </aside>
  );
}

export default Sidebar;