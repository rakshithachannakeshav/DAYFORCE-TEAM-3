import { ShieldCheck } from "lucide-react";

// Top bar with the product name.
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
