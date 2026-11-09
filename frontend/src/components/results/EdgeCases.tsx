import type { EdgeCase } from "../../types";

interface Props {
  edgeCases: EdgeCase[];
}

// Lists the boundary and edge-case tests.
function EdgeCases({ edgeCases }: Props) {
  return (
    <section className="result-card">
      <h2>Edge Cases</h2>

      {edgeCases.length === 0 ? (
        <p>No edge cases available.</p>
      ) : (
        <ul className="edge-case-list">
          {edgeCases.map((edgeCase) => (
            <li key={edgeCase.id}>
              <span className="item-id">{edgeCase.id}</span>{" "}
              <span className={`type-badge ${edgeCase.type}`}>
                {edgeCase.type.replace("_", " ")}
              </span>{" "}
              {edgeCase.description}: {edgeCase.expected_result}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default EdgeCases;
