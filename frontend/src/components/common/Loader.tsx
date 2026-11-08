
import { LoaderCircle } from "lucide-react";

interface Props {
  message: string;
}

function Loader({ message }: Props) {
  return (
    <div className="loader" role="status">
      <LoaderCircle className="loader-icon" size={18} />
      <span>{message}</span>
    </div>
  );
}

export default Loader;
