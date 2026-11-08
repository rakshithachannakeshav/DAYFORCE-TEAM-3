import { ShieldCheck, Bell, UserCircle } from "lucide-react";

function Navbar() {
  return (
    <header className="navbar">
      <div className="navbar-brand">
        <ShieldCheck size={26} />
        <span>TestCraft AI</span>
      </div>

      <div className="navbar-actions">
        <button className="icon-button" aria-label="Notifications">
          <Bell size={20} />
        </button>

        <div className="user-profile">
          <UserCircle size={25} />
          <span>Workspace</span>
        </div>
      </div>
    </header>
  );
}

export default Navbar;