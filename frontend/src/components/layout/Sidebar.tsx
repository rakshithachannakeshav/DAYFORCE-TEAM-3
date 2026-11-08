import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  FileText,
  GitBranch,
  Settings
} from "lucide-react";

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

      <div className="sidebar-bottom">
        <NavLink to="/settings" className="sidebar-link">
          <Settings size={19} />
          <span>Settings</span>
        </NavLink>
      </div>

    </aside>
  );
}

export default Sidebar;