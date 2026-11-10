import type { TestScenario } from "../../types";

interface Props {
  scenarios: TestScenario[];
}

// Lists every generated test scenario with its type, values and the
// recommended way to automate it.
function TestScenarios({ scenarios }: Props) {
  return (
    <section className="result-card">
      <h2>Test Scenarios</h2>

      {scenarios.length === 0 ? (
        <p>No test scenarios available.</p>
      ) : (
        <div className="table-wrapper">
          <table className="scenario-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Criterion</th>
                <th>Scenario</th>
                <th>Expected Result</th>
                <th>Type</th>
                <th>Automation</th>
              </tr>
            </thead>

            <tbody>
              {scenarios.map((scenario) => (
                <tr key={scenario.id}>
                  <td>{scenario.id}</td>
                  <td>{scenario.criterion_id}</td>
                  <td>
                    {scenario.scenario}
                    {scenario.test_data.length > 0 && (
                      <ul className="test-data-list">
                        {scenario.test_data.map((value) => (
                          <li key={value}>{value}</li>
                        ))}
                      </ul>
                    )}
                  </td>
                  <td>{scenario.expected_result}</td>
                  <td>
                    <span
                      className={`type-badge ${scenario.type}`}
                    >
                      {scenario.type.replace("_", " ")}
                    </span>
                  </td>
                  <td>
                    {scenario.automation.automatable ? (
                      <>
                        <span className="automation-level">
                          {scenario.automation.level}
                        </span>
                        {scenario.automation.suggested_tool &&
                          ` · ${scenario.automation.suggested_tool}`}
                      </>
                    ) : (
                      <span className="automation-level">manual</span>
                    )}
                    {scenario.automation.rationale && (
                      <p className="automation-rationale">
                        {scenario.automation.rationale}
                      </p>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default TestScenarios;