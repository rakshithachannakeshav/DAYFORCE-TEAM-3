// Tests for mapping UI text to the request and the response to the view model.
import { describe, expect, it } from "vitest";
import { mockResults } from "../data/mockResults";
import { buildRequirementInput, toGenerationResponse } from "./adapter";

describe("buildRequirementInput", () => {
  it("sends plain text as the description only", () => {
    expect(buildRequirementInput("  Users can reset their password.  ")).toEqual({
      description: "Users can reset their password.",
    });
  });

  it("turns bullet and numbered lines into business rules", () => {
    const text = [
      "Managers approve leave requests.",
      "- A rejection requires a reason of at least 10 characters.",
      "2. Only the direct manager can approve.",
    ].join("\r\n");

    expect(buildRequirementInput(text)).toEqual({
      description: "Managers approve leave requests.",
      business_rules: [
        "A rejection requires a reason of at least 10 characters.",
        "Only the direct manager can approve.",
      ],
    });
  });

  it("keeps the text as the description when every line is a bullet", () => {
    const input = buildRequirementInput("- Users can log in with an email.");

    expect(input).toEqual({ description: "- Users can log in with an email." });
  });

  it("does not treat a hyphen inside a sentence as a rule", () => {
    expect(buildRequirementInput("Self-service users - admins too - can log in.")).toEqual({
      description: "Self-service users - admins too - can log in.",
    });
  });
});

describe("toGenerationResponse", () => {
  const view = toGenerationResponse(mockResults);

  it("maps scenarios and keeps all four test types", () => {
    expect(view.test_scenarios[2]).toEqual({
      id: "TC-003",
      criterion_id: "AC-2",
      scenario: "Boundary values for 'at least 8 characters'",
      steps: ["Submit one password for each value in test_data"],
      test_data: ["7 characters -> rejected", "8 characters -> accepted"],
      expected_result: "Each value behaves as listed in test_data",
      type: "boundary",
      priority: "high",
      automation: {
        automatable: true,
        level: "api",
        suggested_tool: "pytest",
        rationale: "Mock data",
      },
    });
    expect(view.test_scenarios.map((scenario) => scenario.type)).toEqual([
      "positive",
      "negative",
      "boundary",
      "edge_case",
    ]);
  });

  it("maps edge cases, ambiguities and assumptions", () => {
    expect(view.edge_cases[1]).toEqual({
      id: "TC-004",
      criterion_id: "AC-1",
      type: "edge_case",
      description: "Login with an empty password",
      expected_result: "A validation message is shown",
    });
    expect(view.ambiguities[0].question).toBe(
      "Should accounts be locked after repeated failed login attempts?"
    );
    expect(view.assumptions).toEqual([]);
  });

  it("uses the backend's traceability and coverage instead of recomputing", () => {
    expect(view.traceability[1]).toEqual({
      criterion_id: "AC-2",
      criterion: "The password must be at least 8 characters.",
      test_case_ids: ["TC-003"],
      status: "partial",
      missing: ["a positive test", "a negative test"],
    });
    expect(view.coverage).toEqual({
      validated_percent: 50,
      generated_percent: 100,
      gaps: ["AC-2 has no positive or negative test"],
    });
  });

  it("derives the status from needs_clarification", () => {
    expect(view.status).toBe("ready");
    expect(
      toGenerationResponse({ ...mockResults, needs_clarification: true }).status
    ).toBe("needs_clarification");
  });
});
