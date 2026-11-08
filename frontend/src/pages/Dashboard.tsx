import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useGeneration } from "../hooks/useGeneration";
import { mockResults } from "../data/mockResults";
import {
  FileText,
  Sparkles,
  ArrowRight,
  GitBranch
} from "lucide-react";

function Dashboard() {
  const [requirement, setRequirement] = useState("");
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const navigate = useNavigate();
  const {
  setRequirement: saveRequirement,
  setResults
} = useGeneration();

  const MAX_LENGTH = 2000;

  const handleGenerate = () => {
    setError("");
    setSubmitted(false);

    if (!requirement.trim()) {
      setError("Please enter a product requirement.");
      return;
    }

    if (requirement.trim().length < 10) {
      setError("Please provide a more detailed requirement.");
      return;
    }

    setSubmitted(true);
    saveRequirement(requirement.trim());
    setResults(mockResults);
    navigate("/results");
    console.log("Requirement submitted:", requirement);
  };

  const handleChange = (value: string) => {
    if (value.length <= MAX_LENGTH) {
      setRequirement(value);
      setError("");
      setSubmitted(false);
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
          <p className="error-message">
            {error}
          </p>
        )}

        {submitted && (
          <p className="success-message">
            Requirement captured successfully! Backend integration is the next step.
          </p>
        )}

        <div className="card-footer">

          <span>
            Be as specific as possible for better results.
          </span>

          <button
            className="generate-button"
            onClick={handleGenerate}
            disabled={!requirement.trim()}
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
            Generate positive and negative testing scenarios.
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