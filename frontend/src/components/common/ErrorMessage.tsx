interface Props {
  message: string;
  details?: string[];
}

// Shows an error message with any detail lines from the backend.
function ErrorMessage({ message, details = [] }: Props) {
  return (
    <div className="error-message" role="alert">
      <p>{message}</p>

      {details.length > 0 && (
        <ul className="error-details">
          {details.map((detail, index) => (
            <li key={index}>{detail}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default ErrorMessage;
