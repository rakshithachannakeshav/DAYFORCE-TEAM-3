import { LoaderCircle } from "lucide-react";

interface Props {
  message: string;
}

// Spinner with a status message.
function Loader({ message }: Props) {
  return (
    <div className="loader" role="status">
      <LoaderCircle className="loader-icon" size={18} />
      <span>{message}</span>
    </div>
  );
}

export default Loader;
