
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

// Export complete results as JSON
export function exportJSON(data: GenerationResponse) {
  const json = JSON.stringify(data, null, 2);

  downloadFile(
    json,
    "generated-test-results.json",
    "application/json"
  );
}

// Export test scenarios as CSV
export function exportCSV(data: GenerationResponse) {

  const headers = [
    "Test Case ID",
    "Acceptance Criteria ID",
    "Scenario",
    "Expected Result",
    "Type"
  ];

  const rows = data.test_scenarios.map((scenario) => [
    scenario.id,
    scenario.criterion_id,
    scenario.scenario,
    scenario.expected_result,
    scenario.type
  ]);

  const csvContent = [
    headers.map(escapeCSV).join(","),
    ...rows.map((row) =>
      row.map(escapeCSV).join(",")
    )
  ].join("\r\n");

  // BOM helps spreadsheet applications recognize UTF-8.
  downloadFile(
    "\uFEFF" + csvContent,
    "generated-test-scenarios.csv",
    "text/csv;charset=utf-8;"
  );
}