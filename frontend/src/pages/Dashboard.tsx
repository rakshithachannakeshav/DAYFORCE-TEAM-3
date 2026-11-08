import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import ErrorMessage from "../components/common/ErrorMessage";
import Loader from "../components/common/Loader";
import { useGeneration } from "../hooks/useGeneration";
import { GenerationError, generateTests } from "../services/api";
import {
  FileText,
  Sparkles,
  ArrowRight,
  GitBranch
} from "lucide-react";

const MAX_LENGTH = 2000;

// Same minimums as llm_pipeline/validation.py, so short input fails without a request.
const MIN_CHARS = 15;
const MIN_WORDS = 4;

function Dashboard() {
  const [requirement, setRequirement] = useState("");
  const [error, setError] = useState("");
  const [errorDetails, setErrorDetails] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const pendingRequest = useRef<AbortController | null>(null);
  const navigate = useNavigate();
  const { setRequirement: saveRequirement, setResults } = useGeneration();

  // Leaving the page cancels the wait, so a late response cannot redirect the user.
  useEffect(() => () => pendingRequest.current?.abort(), []);

  const handleGenerate = async () => {
    setError("");
    setErrorDetails([]);

    const text = requirement.trim();

    if (!text) {
      setError("Please enter a product requirement.");
      return;
    }

    if (
      text.length < MIN_CHARS ||
      (text.match(/[A-Za-z]{2,}/g) ?? []).length < MIN_WORDS
    ) {
      setError("Please provide a more detailed requirement.");
      return;
    }

    const controller = new AbortController();
    pendingRequest.current = controller;

    setLoading(true);
    setResults(null);
    saveRequirement(text);

    try {
      setResults(await generateTests(text, controller.signal));
      navigate("/results");
    } catch (err) {
      if (axios.isCancel(err)) {
        return;
      }
      setError(err instanceof Error ? err.message : "Something went wrong while generating tests.");
      setErrorDetails(err instanceof GenerationError ? err.details : []);
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (value: string) => {
    if (value.length <= MAX_LENGTH) {
      setRequirement(value);
      setError("");
      setErrorDetails([]);
    }
  };

  return (
    <div className="dashboard">

      <div className="dashboard-header">
        <div>
          <p className="welcome-text">
            WORKSPACE / DASHBOARD
          </p>

          <h1>Product Requirements-to-Test Assistant</h1>

          <p className="subtitle">
            Transform product requirements into acceptance criteria,
            test scenarios and edge cases.
          </p>
        </div>
      </div>

      <div className="requirement-card">

        <div className="card-heading">

          <div className="heading-icon">
            <FileText size={22} />
          </div>

          <div>
            <h2>Enter your product requirement</h2>

            <p>
              Describe what your product or feature should accomplish.
            </p>
          </div>

        </div>

        <textarea
          className="requirement-textarea"
          placeholder="Example: As a user, I want to reset my password using my registered email address..."
          value={requirement}
          onChange={(e) => handleChange(e.target.value)}
        />

        <div className="character-count">
          {requirement.length}/{MAX_LENGTH} characters
        </div>

        {error && (
          <ErrorMessage message={error} details={errorDetails} />
        )}

        {loading && (
          <Loader message="Generating tests. A local model can take several minutes." />
        )}

        <div className="card-footer">

          <span>
            Be as specific as possible. Put each business rule on its own line starting with "- ".
          </span>

          <button
            className="generate-button"
            onClick={handleGenerate}
            disabled={!requirement.trim() || loading}
          >
            <Sparkles size={18} />

            Generate Tests

            <ArrowRight size={17} />
          </button>

        </div>

      </div>

      <div className="info-grid">

        <div className="info-card">
          <FileText size={22} />

          <h3>Acceptance Criteria</h3>

          <p>
            Define measurable conditions for feature completion.
          </p>
        </div>

        <div className="info-card">
          <Sparkles size={22} />

          <h3>Test Scenarios</h3>

          <p>
            Generate positive, negative, boundary and edge case scenarios.
          </p>
        </div>

        <div className="info-card">
          <GitBranch size={22} />

          <h3>Traceability</h3>

          <p>
            Connect requirements with their corresponding tests.
          </p>
        </div>

      </div>

    </div>
  );
}

export default Dashboard;