
import type { TestScenario } from "../../types";

interface Props {
  scenarios: TestScenario[];
}

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