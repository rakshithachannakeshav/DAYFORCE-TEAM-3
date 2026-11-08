
import type { BackendGenerationResult } from "../types";

// Used only when VITE_USE_MOCK=true. It has the API's shape, so mock mode goes
// through the same adapter as real responses.
const automation = {
  automatable: true,
  level: "api",
  suggested_tool: "pytest",
  rationale: "Mock data"
};

const scenarioDefaults = {
  requirement_id: "REQ-MOCK",
  preconditions: ["A registered user exists"],
  test_data: [] as string[],
  priority: "high" as const,
  automation
};

export const mockResults: BackendGenerationResult = {
  requirement_id: "REQ-MOCK",
  title: "Mock login requirement",
  original_requirement: "Users can log in with an email and a password of at least 8 characters.",
  needs_clarification: false,

  ambiguities: [
    {
      id: "AMB-1",
      text: "log in",
      issue: "The requirement does not specify account lockout behavior.",
      clarification_question: "Should accounts be locked after repeated failed login attempts?",
      severity: "medium",
      source: "llm"
    }
  ],

  assumptions: [],

  acceptance_criteria: [
    {
      id: "AC-1",
      description: "Users can log in with a valid email and password.",
      given: "a registered user",
      when: "valid credentials are submitted",
      then: "the user is authenticated",
      source: "explicit",
      assumption_ids: []
    },
    {
      id: "AC-2",
      description: "The password must be at least 8 characters.",
      given: "a user choosing a password",
      when: "the password is submitted",
      then: "shorter passwords are rejected",
      source: "explicit",
      assumption_ids: []
    }
  ],

  test_scenarios: [
    {
      ...scenarioDefaults,
      test_case_id: "TC-001",
      title: "Login using valid credentials",
      acceptance_criterion_id: "AC-1",
      test_type: "positive",
      test_steps: ["Submit a valid email and password"],
      expected_result: "User is authenticated successfully"
    },
    {
      ...scenarioDefaults,
      test_case_id: "TC-002",
      title: "Login using an incorrect password",
      acceptance_criterion_id: "AC-1",
      test_type: "negative",
      test_steps: ["Submit a valid email and a wrong password"],
      expected_result: "Authentication is rejected"
    },
    {
      ...scenarioDefaults,
      test_case_id: "TC-003",
      title: "Boundary values for 'at least 8 characters'",
      acceptance_criterion_id: "AC-2",
      test_type: "boundary",
      test_steps: ["Submit one password for each value in test_data"],
      test_data: ["7 characters -> rejected", "8 characters -> accepted"],
      expected_result: "Each value behaves as listed in test_data"
    },
    {
      ...scenarioDefaults,
      test_case_id: "TC-004",
      title: "Login with an empty password",
      acceptance_criterion_id: "AC-1",
      test_type: "edge_case",
      test_steps: ["Submit a valid email and an empty password"],
      expected_result: "A validation message is shown"
    }
  ],

  edge_cases: [
    {
      test_case_id: "TC-003",
      acceptance_criterion_id: "AC-2",
      test_type: "boundary",
      description: "Boundary values for 'at least 8 characters'",
      expected_result: "Each value behaves as listed in test_data"
    },
    {
      test_case_id: "TC-004",
      acceptance_criterion_id: "AC-1",
      test_type: "edge_case",
      description: "Login with an empty password",
      expected_result: "A validation message is shown"
    }
  ],

  traceability: [
    {
      requirement_id: "REQ-MOCK",
      acceptance_criterion_id: "AC-1",
      acceptance_criterion: "Users can log in with a valid email and password.",
      test_case_ids: ["TC-001", "TC-002", "TC-004"],
      test_types: ["edge_case", "negative", "positive"],
      covered: true,
      business_rules: [],
      has_positive: true,
      has_negative: true,
      boundary_required: false,
      has_boundary: false,
      not_applicable: [],
      blocked_by: [],
      status: "validated",
      missing: []
    },
    {
      requirement_id: "REQ-MOCK",
      acceptance_criterion_id: "AC-2",
      acceptance_criterion: "The password must be at least 8 characters.",
      test_case_ids: ["TC-003"],
      test_types: ["boundary"],
      covered: true,
      business_rules: [],
      has_positive: false,
      has_negative: false,
      boundary_required: true,
      has_boundary: true,
      not_applicable: [],
      blocked_by: [],
      status: "partial",
      missing: ["a positive test", "a negative test"]
    }
  ],

  coverage: {
    total_acceptance_criteria: 2,
    covered_acceptance_criteria: 2,
    coverage_percent: 50,
    scenarios_by_type: { positive: 1, negative: 1, boundary: 1, edge_case: 1 },
    generated_coverage_percent: 100,
    validated_acceptance_criteria: 1,
    blocked_acceptance_criteria: 0,
    assumption_criteria: 0,
    rule_coverage_percent: null,
    gaps: ["AC-2 has no positive or negative test"]
  },

  metadata: {
    model: "mock",
    prompt_version: "mock",
    attempts: 1,
    duration_ms: 0,
    warnings: []
  }
};
