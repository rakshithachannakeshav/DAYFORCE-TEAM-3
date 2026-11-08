// ---------------------------------------------------------------------------
// Backend contract: POST /api/llm/generate (mirrors llm_pipeline/schemas.py)
// ---------------------------------------------------------------------------

export interface RequirementInput {
  description: string;
  business_rules?: string[];
}

export type ScenarioType = "positive" | "negative" | "boundary" | "edge_case";
export type Severity = "high" | "medium" | "low";
export type CriterionStatus =
  | "validated"
  | "partial"
  | "untested"
  | "needs_clarification"
  | "assumption";

export interface BackendAmbiguity {
  id: string;
  text: string;
  issue: string;
  clarification_question: string;
  severity: Severity;
  source: "rule" | "llm";
}

export interface BackendAssumption {
  id: string;
  statement: string;
  reason: string;
}

export interface BackendCriterion {
  id: string;
  description: string;
  given: string;
  when: string;
  then: string;
  source: "explicit" | "assumption";
  assumption_ids: string[];
}

export interface BackendAutomation {
  automatable: boolean;
  level: string;
  suggested_tool: string;
  rationale: string;
}

export interface BackendScenario {
  test_case_id: string;
  title: string;
  requirement_id: string;
  acceptance_criterion_id: string;
  test_type: ScenarioType;
  preconditions: string[];
  test_steps: string[];
  test_data: string[];
  expected_result: string;
  priority: Severity;
  automation: BackendAutomation;
}

export interface BackendEdgeCase {
  test_case_id: string;
  acceptance_criterion_id: string;
  test_type: "boundary" | "edge_case";
  description: string;
  expected_result: string;
}

export interface BackendTraceabilityLink {
  requirement_id: string;
  acceptance_criterion_id: string;
  acceptance_criterion: string;
  test_case_ids: string[];
  test_types: ScenarioType[];
  covered: boolean;
  business_rules: string[];
  has_positive: boolean;
  has_negative: boolean;
  boundary_required: boolean;
  has_boundary: boolean;
  not_applicable: string[];
  blocked_by: string[];
  status: CriterionStatus;
  missing: string[];
}

export interface BackendCoverage {
  total_acceptance_criteria: number;
  covered_acceptance_criteria: number;
  coverage_percent: number;
  scenarios_by_type: Record<string, number>;
  generated_coverage_percent: number;
  validated_acceptance_criteria: number;
  blocked_acceptance_criteria: number;
  assumption_criteria: number;
  rule_coverage_percent: number | null;
  gaps: string[];
}

export interface BackendGenerationResult {
  requirement_id: string;
  title: string | null;
  original_requirement: string;
  needs_clarification: boolean;
  ambiguities: BackendAmbiguity[];
  assumptions: BackendAssumption[];
  acceptance_criteria: BackendCriterion[];
  test_scenarios: BackendScenario[];
  edge_cases: BackendEdgeCase[];
  traceability: BackendTraceabilityLink[];
  coverage: BackendCoverage;
  metadata: {
    model: string;
    prompt_version: string;
    attempts: number;
    duration_ms: number;
    warnings: string[];
  };
}

// ---------------------------------------------------------------------------
// View model used by the Results and Traceability pages and by the exports
// ---------------------------------------------------------------------------

export interface AcceptanceCriterion {
  id: string;
  description: string;
  source: "explicit" | "assumption";
}

export interface TestScenario {
  id: string;
  criterion_id: string;
  scenario: string;
  steps: string[];
  test_data: string[];
  expected_result: string;
  type: ScenarioType;
  priority: Severity;
}

export interface EdgeCase {
  id: string;
  criterion_id: string;
  type: "boundary" | "edge_case";
  description: string;
  expected_result: string;
}

export interface Ambiguity {
  id: string;
  text: string;
  issue: string;
  question: string;
  severity: Severity;
}

export interface TraceabilityRow {
  criterion_id: string;
  criterion: string;
  test_case_ids: string[];
  status: CriterionStatus;
  missing: string[];
}

export interface CoverageView {
  validated_percent: number;
  generated_percent: number;
  gaps: string[];
}

export interface GenerationResponse {
  requirement_id: string;
  status: "ready" | "needs_clarification";
  acceptance_criteria: AcceptanceCriterion[];
  test_scenarios: TestScenario[];
  edge_cases: EdgeCase[];
  ambiguities: Ambiguity[];
  assumptions: string[];
  traceability: TraceabilityRow[];
  coverage: CoverageView;
  // The untouched API response; the JSON export writes this so nothing is lost.
  raw: BackendGenerationResult;
}
