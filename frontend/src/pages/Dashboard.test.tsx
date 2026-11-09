// Tests for submitting a requirement from the home page.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GenerationProvider } from "../context/GenerationProvider";
import { mockResults } from "../data/mockResults";
import { useGeneration } from "../hooks/useGeneration";
import { toGenerationResponse } from "../services/adapter";
import { GenerationError, generateTests } from "../services/api";
import Dashboard from "./Dashboard";

vi.mock("../services/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../services/api")>()),
  generateTests: vi.fn(),
}));

const generateMock = vi.mocked(generateTests);

function ResultsProbe() {
  const { results } = useGeneration();
  return <p>Results for {results?.requirement_id}</p>;
}

function renderDashboard() {
  render(
    <MemoryRouter>
      <GenerationProvider>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/results" element={<ResultsProbe />} />
        </Routes>
      </GenerationProvider>
    </MemoryRouter>
  );
}

function submit(text: string) {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /generate tests/i }));
}

const VALID_TEXT = "Users can reset their password by email.";

describe("Dashboard", () => {
  beforeEach(() => {
    generateMock.mockReset();
  });

  afterEach(cleanup);

  it("disables the button until something is typed", () => {
    renderDashboard();

    const button = screen.getByRole("button", { name: /generate tests/i }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "x" } });
    expect(button.disabled).toBe(false);
  });

  it.each(["Too short", "1234567890 12345 67890"])(
    "rejects %j without calling the API",
    (text) => {
      renderDashboard();

      submit(text);

      expect(screen.getByRole("alert").textContent).toContain("more detailed requirement");
      expect(generateMock).not.toHaveBeenCalled();
    }
  );

  it("shows a loader while waiting, then opens the results", async () => {
    let finish!: (value: ReturnType<typeof toGenerationResponse>) => void;
    generateMock.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    renderDashboard();

    submit(VALID_TEXT);

    expect(screen.getByRole("status").textContent).toContain("Generating tests");
    expect((screen.getByRole("button", { name: /generate tests/i }) as HTMLButtonElement).disabled).toBe(true);
    expect(generateMock.mock.calls[0][0]).toBe(VALID_TEXT);

    finish(toGenerationResponse(mockResults));

    expect(await screen.findByText("Results for REQ-MOCK")).toBeTruthy();
  });

  it("shows the API error and its details, and allows a retry", async () => {
    generateMock.mockRejectedValue(
      new GenerationError("Cannot connect to Ollama.", ["call 1: refused"])
    );
    renderDashboard();

    submit(VALID_TEXT);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Cannot connect to Ollama.");
    expect(alert.textContent).toContain("call 1: refused");
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect((screen.getByRole("button", { name: /generate tests/i }) as HTMLButtonElement).disabled).toBe(false);
  });
});
