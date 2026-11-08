
import type {
  AcceptanceCriterion,
  TestScenario
} from "../../types";

interface Props {
  criteria: AcceptanceCriterion[];
  scenarios: TestScenario[];
}

function TraceabilityMatrix({ criteria, scenarios }: Props) {

  const coveredCriteria = criteria.filter((criterion) =>
    scenarios.some(
      (scenario) => scenario.criterion_id === criterion.id
    )
  );

  const coverage = criteria.length > 0
    ? Math.round((coveredCriteria.length / criteria.length) * 100)
    : 0;

  return (
    <section className="result-card">

      <h2>Requirement Traceability Matrix</h2>

      <div className="coverage-section">
        <div className="coverage-header">
          <span>Acceptance Criteria Coverage</span>
          <strong>{coverage}%</strong>
        </div>

        <div className="coverage-bar">
          <div
            className="coverage-fill"
            style={{ width: `${coverage}%` }}
          />
        </div>
      </div>

      <div className="table-wrapper">
        <table className="scenario-table">

          <thead>
            <tr>
              <th>Acceptance Criterion</th>
              <th>Mapped Test Scenarios</th>
              <th>Coverage Status</th>
            </tr>
          </thead>

          <tbody>
            {criteria.map((criterion) => {

              const mappedTests = scenarios.filter(
                (scenario) =>
                  scenario.criterion_id === criterion.id
              );

              return (
                <tr key={criterion.id}>

                  <td>
                    <strong>{criterion.id}</strong>
                    <p>{criterion.description}</p>
                  </td>

                  <td>
                    {mappedTests.length > 0
                      ? mappedTests.map((test) => (
                          <span
                            className="mapped-test"
                            key={test.id}
                          >
                            {test.id}
                          </span>
                        ))
                      : "No tests mapped"}
                  </td>

                  <td>
                    <span
                      className={`coverage-status ${
                        mappedTests.length > 0
                          ? "covered"
                          : "uncovered"
                      }`}
                    >
                      {mappedTests.length > 0
                        ? "Covered"
                        : "Not Covered"}
                    </span>
                  </td>

                </tr>
              );
            })}
          </tbody>

        </table>
      </div>

    </section>
  );
}

export default TraceabilityMatrix;