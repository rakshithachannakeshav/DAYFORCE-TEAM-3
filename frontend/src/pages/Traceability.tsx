
import { mockResults } from "../data/mockResults";
import TraceabilityMatrix from "../components/traceability/TraceabilityMatrix";

function Traceability() {
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

      <TraceabilityMatrix
        criteria={mockResults.acceptance_criteria}
        scenarios={mockResults.test_scenarios}
      />

    </div>
  );
}

export default Traceability;