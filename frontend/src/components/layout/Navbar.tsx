import { ShieldCheck } from "lucide-react";

function Navbar() {
  return (
    <header className="navbar">
      <div className="navbar-brand">
        <ShieldCheck size={26} />
        <span>TestCraft AI</span>
      </div>
    </header>
  );
}

export default Navbar;
