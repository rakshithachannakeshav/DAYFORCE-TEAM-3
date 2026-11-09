import { Link } from "react-router-dom";

// Shown for any unknown URL.
function NotFound() {
  return (
    <div className="dashboard">
      <h1>404 - Page Not Found</h1>
      <Link to="/">Return to Dashboard</Link>
    </div>
  );
}

export default NotFound;