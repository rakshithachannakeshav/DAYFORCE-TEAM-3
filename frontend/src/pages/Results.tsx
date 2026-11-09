import AcceptanceCriteria from "../components/results/AcceptanceCriteria";
import TestScenarios from "../components/results/TestScenarios";
import EdgeCases from "../components/results/EdgeCases";
import { Download, FileJson, FileSpreadsheet } from "lucide-react";
import { useGeneration } from "../hooks/useGeneration";
import { exportCSV, exportJSON } from "../utils/export";

// Shows the generated criteria, scenarios and clarifications, with CSV and JSON export.
function Results() {
  const { requirement, results } = useGeneration();

  if (!results) {
    return <p>No results available. Please submit a requirement first.</p>;
  }

  return (
    <div className="dashboard">

      <div className="dashboard-header">
        <p className="welcome-text">
          WORKSPACE / GENERATED TESTS
        </p>

        <h1>Generated Test Results</h1>

        <p className="subtitle">
          Review acceptance criteria, test scenarios and edge cases.
        </p>
      </div>

      <div className="export-actions">
        <div className="requirement-preview">
          <h3>Submitted Requirement</h3>
          <p>{requirement}</p>
        </div>

        <button
          className="export-button"
          onClick={() => exportCSV(results)}
        >
          <FileSpreadsheet size={17} />
          Export CSV
        </button>

        <button
          className="export-button primary-export"
          onClick={() => exportJSON(results)}
        >
          <FileJson size={17} />
          Export JSON
          <Download size={16} />
        </button>
      </div>

      {results.status === "needs_clarification" && (
        <p className="clarification-banner" role="status">
          This requirement needs clarification. Criteria blocked by an ambiguity
          are not counted as validated until the questions below are answered.
        </p>
      )}

      <div className="results-summary">
        <div className="summary-card">
          <h2>{results.acceptance_criteria.length}</h2>
          <p>Acceptance Criteria</p>
        </div>

        <div className="summary-card">
          <h2>{results.test_scenarios.length}</h2>
          <p>Test Scenarios</p>
        </div>

        <div className="summary-card">
          <h2>{results.edge_cases.length}</h2>
          <p>Edge Cases</p>
        </div>
      </div>

      <AcceptanceCriteria
        criteria={results.acceptance_criteria}
      />

      <TestScenarios
        scenarios={results.test_scenarios}
      />

      <EdgeCases
        edgeCases={results.edge_cases}
      />

      {results.ambiguities.length > 0 && (
        <section className="result-card">
          <h2>Ambiguities & Clarifications</h2>

          {results.ambiguities.map((item) => (
            <div className="result-text" key={item.id}>
              <p>
                <strong>{item.id} ({item.severity}):</strong> {item.text}: {item.issue}
              </p>
              <p>
                <strong>Question:</strong> {item.question}
              </p>
            </div>
          ))}
        </section>
      )}

      {results.assumptions.length > 0 && (
        <section className="result-card">
          <h2>Assumptions</h2>

          <ul className="edge-case-list">
            {results.assumptions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      )}

    </div>
  );
}

export default Results;