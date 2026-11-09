import { Link } from "react-router-dom";
import TraceabilityMatrix from "../components/traceability/TraceabilityMatrix";
import { useGeneration } from "../hooks/useGeneration";

// Shows how acceptance criteria map to test scenarios.
function Traceability() {
  const { results } = useGeneration();

  return (
    <div className="dashboard">

      <div className="dashboard-header">

        <p className="welcome-text">
          WORKSPACE / TRACEABILITY
        </p>

        <h1>Requirement Traceability</h1>

        <p className="subtitle">
          Track how acceptance criteria are connected
          to their corresponding test scenarios.
        </p>

      </div>

      {results ? (
        <TraceabilityMatrix
          rows={results.traceability}
          coverage={results.coverage}
        />
      ) : (
        <section className="result-card">
          <p>
            No results yet. <Link className="text-link" to="/">Submit a requirement</Link> first.
          </p>
        </section>
      )}

    </div>
  );
}

export default Traceability;
