export interface GenerationRequest {
  requirement: string;
}

export interface AcceptanceCriterion {
  id: string;
  description: string;
}

export interface TestScenario {
  id: string;
  criterion_id: string;
  scenario: string;
  expected_result: string;
  type: "positive" | "negative";
}

export interface GenerationResponse {
  status: "ready" | "needs_clarification";
  acceptance_criteria: AcceptanceCriterion[];
  test_scenarios: TestScenario[];
  edge_cases: string[];
  ambiguities: string[];
  clarification_questions: string[];
}