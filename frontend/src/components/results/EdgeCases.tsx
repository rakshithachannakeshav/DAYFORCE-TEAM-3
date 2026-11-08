
interface Props {
  edgeCases: string[];
}

function EdgeCases({ edgeCases }: Props) {
  return (
    <section className="result-card">
      <h2>Edge Cases</h2>

      {edgeCases.length === 0 ? (
        <p>No edge cases available.</p>
      ) : (
        <ul className="edge-case-list">
          {edgeCases.map((edgeCase, index) => (
            <li key={index}>{edgeCase}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default EdgeCases;