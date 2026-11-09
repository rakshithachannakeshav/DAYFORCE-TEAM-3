// Tests for the CSV and JSON export content.
import { describe, expect, it } from "vitest";
import { mockResults } from "../data/mockResults";
import { toGenerationResponse } from "../services/adapter";
import { buildCSV, buildJSON } from "./export";

const view = toGenerationResponse(mockResults);

describe("buildCSV", () => {
  it("writes a header and one row per scenario", () => {
    const lines = buildCSV(view).split("\r\n");

    expect(lines).toHaveLength(1 + mockResults.test_scenarios.length);
    expect(lines[0]).toBe(
      '"Test Case ID","Requirement ID","Acceptance Criteria ID","Scenario","Steps","Test Data","Expected Result","Type","Priority"'
    );
    expect(lines[3]).toBe(
      `"TC-003","REQ-MOCK","AC-2","Boundary values for 'at least 8 characters'","Submit one password for each value in test_data","7 characters -> rejected | 8 characters -> accepted","Each value behaves as listed in test_data","boundary","high"`
    );
  });

  it("escapes double quotes", () => {
    const quoted = {
      ...view,
      test_scenarios: [{ ...view.test_scenarios[0], scenario: 'Enter "admin"' }],
    };

    expect(buildCSV(quoted).split("\r\n")[1]).toContain('"Enter ""admin"""');
  });
});

describe("buildJSON", () => {
  it("writes the complete API response", () => {
    expect(JSON.parse(buildJSON(view))).toEqual(mockResults);
  });
});
