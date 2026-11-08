
import type {
  CoverageView,
  CriterionStatus,
  TraceabilityRow
} from "../../types";

interface Props {
  rows: TraceabilityRow[];
  coverage: CoverageView;
}

const STATUS_LABELS: Record<CriterionStatus, string> = {
  validated: "Validated",
  partial: "Partial",
  untested: "Not Covered",
  needs_clarification: "Needs Clarification",
  assumption: "Assumption"
};

function TraceabilityMatrix({ rows, coverage }: Props) {
  return (
    <section className="result-card">

      <h2>Requirement Traceability Matrix</h2>

      <div className="coverage-section">
        <div className="coverage-header">
          <span>Validated Coverage</span>
          <strong>{coverage.validated_percent}%</strong>
        </div>

        <div className="coverage-bar">
          <div
            className="coverage-fill"
            style={{ width: `${coverage.validated_percent}%` }}
          />
        </div>

        <p className="coverage-note">
          {coverage.generated_percent}% of criteria have at least one test.
          Validated criteria also have the required positive, negative and
          boundary tests and no unresolved ambiguity.
        </p>
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
            {rows.map((row) => (
              <tr key={row.criterion_id}>

                <td>
                  <strong>{row.criterion_id}</strong>
                  <p>{row.criterion}</p>
                </td>

                <td>
                  {row.test_case_ids.length > 0
                    ? row.test_case_ids.map((id) => (
                        <span
                          className="mapped-test"
                          key={id}
                        >
                          {id}
                        </span>
                      ))
                    : "No tests mapped"}
                </td>

                <td>
                  <span className={`coverage-status ${row.status}`}>
                    {STATUS_LABELS[row.status]}
                  </span>

                  {row.missing.length > 0 && (
                    <p className="coverage-note">
                      Missing: {row.missing.join(", ")}
                    </p>
                  )}
                </td>

              </tr>
            ))}
          </tbody>

        </table>
      </div>

      {coverage.gaps.length > 0 && (
        <div className="coverage-gaps">
          <h3>Remaining Gaps</h3>

          <ul className="edge-case-list">
            {coverage.gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </div>
      )}

    </section>
  );
}

export default TraceabilityMatrix;
