import type {
  BackendGenerationResult,
  GenerationResponse,
  RequirementInput,
} from "../types";

// A bullet or numbered line, capturing the text after the marker.
const RULE_LINE = /^\s*(?:[-*•]|\d+[.)])\s+(.+)$/;

// The UI collects one free-text requirement. Bullet or numbered lines become
// business rules so the pipeline can trace coverage back to each of them; all
// other lines form the description. The pipeline generates the requirement ID.
export function buildRequirementInput(text: string): RequirementInput {
  const description: string[] = [];
  const rules: string[] = [];

  for (const line of text.split(/\r?\n/)) {
    const rule = line.match(RULE_LINE);
    if (rule) {
      rules.push(rule[1].trim());
    } else if (line.trim()) {
      description.push(line.trim());
    }
  }

  if (description.length === 0) {
    return { description: text.trim() };
  }

  return rules.length > 0
    ? { description: description.join(" "), business_rules: rules }
    : { description: description.join(" ") };
}

// Maps the API response to the simpler view model the pages and exports use.
export function toGenerationResponse(
  result: BackendGenerationResult
): GenerationResponse {
  return {
    requirement_id: result.requirement_id,
    status: result.needs_clarification ? "needs_clarification" : "ready",

    acceptance_criteria: result.acceptance_criteria.map((criterion) => ({
      id: criterion.id,
      description: criterion.description,
      source: criterion.source,
    })),

    test_scenarios: result.test_scenarios.map((scenario) => ({
      id: scenario.test_case_id,
      criterion_id: scenario.acceptance_criterion_id,
      scenario: scenario.title,
      steps: scenario.test_steps,
      test_data: scenario.test_data,
      expected_result: scenario.expected_result,
      type: scenario.test_type,
      priority: scenario.priority,
      automation: scenario.automation,
    })),

    edge_cases: result.edge_cases.map((edgeCase) => ({
      id: edgeCase.test_case_id,
      criterion_id: edgeCase.acceptance_criterion_id,
      type: edgeCase.test_type,
      description: edgeCase.description,
      expected_result: edgeCase.expected_result,
    })),

    ambiguities: result.ambiguities.map((ambiguity) => ({
      id: ambiguity.id,
      text: ambiguity.text,
      issue: ambiguity.issue,
      question: ambiguity.clarification_question,
      severity: ambiguity.severity,
    })),

    assumptions: result.assumptions.map((assumption) => assumption.statement),

    traceability: result.traceability.map((link) => ({
      criterion_id: link.acceptance_criterion_id,
      criterion: link.acceptance_criterion,
      test_case_ids: link.test_case_ids,
      status: link.status,
      missing: link.missing,
    })),

    coverage: {
      validated_percent: result.coverage.coverage_percent,
      generated_percent: result.coverage.generated_coverage_percent,
      gaps: result.coverage.gaps,
    },

    raw: result,
  };
}
