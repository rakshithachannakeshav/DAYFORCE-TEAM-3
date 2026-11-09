import type { AcceptanceCriterion } from "../../types";

interface Props {
  criteria: AcceptanceCriterion[];
}

// Lists the acceptance criteria generated for the requirement.
function AcceptanceCriteria({ criteria }: Props) {
  return (
    <section className="result-card">
      <h2>Acceptance Criteria</h2>

      {criteria.length === 0 ? (
        <p>No acceptance criteria available.</p>
      ) : (
        <div className="criteria-list">
          {criteria.map((criterion) => (
            <div className="criterion-item" key={criterion.id}>
              <span className="item-id">{criterion.id}</span>
              <p>
                {criterion.description}
                {criterion.source === "assumption" && (
                  <span className="assumption-tag"> (assumption)</span>
                )}
              </p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default AcceptanceCriteria;