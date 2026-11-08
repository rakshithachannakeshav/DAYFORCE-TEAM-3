
import type { GenerationResponse } from "../types";

// Download a file in the browser
function downloadFile(
  content: string,
  filename: string,
  mimeType: string
) {
  const blob = new Blob([content], { type: mimeType });

  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");

  link.href = url;
  link.download = filename;

  document.body.appendChild(link);
  link.click();

  document.body.removeChild(link);

  URL.revokeObjectURL(url);
}

// Escape CSV values
function escapeCSV(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

// The complete API response, so the export loses nothing the UI does not show
export function buildJSON(data: GenerationResponse): string {
  return JSON.stringify(data.raw, null, 2);
}

export function buildCSV(data: GenerationResponse): string {
  const headers = [
    "Test Case ID",
    "Requirement ID",
    "Acceptance Criteria ID",
    "Scenario",
    "Steps",
    "Test Data",
    "Expected Result",
    "Type",
    "Priority"
  ];

  const rows = data.test_scenarios.map((scenario) => [
    scenario.id,
    data.requirement_id,
    scenario.criterion_id,
    scenario.scenario,
    scenario.steps.join(" | "),
    scenario.test_data.join(" | "),
    scenario.expected_result,
    scenario.type,
    scenario.priority
  ]);

  return [
    headers.map(escapeCSV).join(","),
    ...rows.map((row) =>
      row.map(escapeCSV).join(",")
    )
  ].join("\r\n");
}

// Export complete results as JSON
export function exportJSON(data: GenerationResponse) {
  downloadFile(
    buildJSON(data),
    "generated-test-results.json",
    "application/json"
  );
}

// Export test scenarios as CSV
export function exportCSV(data: GenerationResponse) {
  // BOM helps spreadsheet applications recognize UTF-8.
  downloadFile(
    "﻿" + buildCSV(data),
    "generated-test-scenarios.csv",
    "text/csv;charset=utf-8;"
  );
}
