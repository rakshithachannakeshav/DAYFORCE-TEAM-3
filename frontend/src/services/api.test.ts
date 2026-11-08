import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockResults } from "../data/mockResults";
import { api, GenerationError, generateTests, toGenerationError } from "./api";

describe("generateTests", () => {
  const originalAdapter = api.defaults.adapter;

  afterEach(() => {
    api.defaults.adapter = originalAdapter;
    vi.unstubAllEnvs();
  });

  it("posts a RequirementInput to /api/llm/generate and adapts the response", async () => {
    const requests: InternalAxiosRequestConfig[] = [];
    api.defaults.adapter = async (config) => {
      requests.push(config);
      return { data: mockResults, status: 200, statusText: "OK", headers: {}, config };
    };

    const view = await generateTests("Users can log in.\n- Passwords have at least 8 characters.");

    expect(requests).toHaveLength(1);
    expect(requests[0].method).toBe("post");
    expect(requests[0].baseURL).toBe("http://localhost:8000");
    expect(requests[0].url).toBe("/api/llm/generate");
    expect(JSON.parse(requests[0].data)).toEqual({
      description: "Users can log in.",
      business_rules: ["Passwords have at least 8 characters."],
    });
    expect(view.requirement_id).toBe("REQ-MOCK");
    expect(view.test_scenarios).toHaveLength(mockResults.test_scenarios.length);
  });

  it("turns a failed request into a GenerationError", async () => {
    api.defaults.adapter = async () => {
      throw new AxiosError("Network Error", "ERR_NETWORK");
    };

    await expect(generateTests("Users can log in with a password.")).rejects.toBeInstanceOf(GenerationError);
  });

  it("returns mock data without a request only when VITE_USE_MOCK is true", async () => {
    const adapter = vi.fn();
    api.defaults.adapter = adapter;
    vi.stubEnv("VITE_USE_MOCK", "true");

    const view = await generateTests("Users can log in with a password.");

    expect(view.requirement_id).toBe("REQ-MOCK");
    expect(adapter).not.toHaveBeenCalled();
  });
});

function httpError(status: number, data: unknown): AxiosError {
  return new AxiosError("failed", "ERR_BAD_RESPONSE", undefined, undefined, {
    status,
    data,
  } as AxiosResponse);
}

describe("toGenerationError", () => {
  it("explains a network error", () => {
    const error = toGenerationError(new AxiosError("Network Error", "ERR_NETWORK"));

    expect(error.message).toContain("Cannot reach the backend");
  });

  it("explains a client timeout", () => {
    const error = toGenerationError(new AxiosError("timeout", "ECONNABORTED"));

    expect(error.message).toContain("timed out");
  });

  it("lists the pipeline's validation problems on a 422", () => {
    const error = toGenerationError(
      httpError(422, {
        error: "invalid_requirement",
        message: "Requirement failed validation",
        details: ["description must contain at least 4 real words"],
      })
    );

    expect(error.message).toContain("rejected");
    expect(error.details).toEqual(["description must contain at least 4 real words"]);
  });

  it("reads FastAPI's request validation format on a 422", () => {
    const error = toGenerationError(
      httpError(422, { detail: [{ loc: ["body", "description"], msg: "Field required" }] })
    );

    expect(error.details).toEqual(["body.description: Field required"]);
  });

  it("shows the backend's Ollama instructions on a 503", () => {
    const message = "Cannot connect to Ollama at http://localhost:11434. Is it running? Try: `ollama serve`";
    const error = toGenerationError(
      httpError(503, { error: "llm_unavailable", message, details: [] })
    );

    expect(error.message).toBe(message);
  });

  it.each([
    [502, "did not produce a valid result"],
    [503, "Check that Ollama is running"],
    [504, "took too long"],
    [500, "HTTP 500"],
  ])("falls back to a clear message on a bare %i", (status, expected) => {
    expect(toGenerationError(httpError(status, undefined)).message).toContain(expected);
  });

  it("includes attempt history on a 502", () => {
    const error = toGenerationError(
      httpError(502, {
        error: "generation_failed",
        message: "Could not generate valid output after 3 attempts",
        details: ["call 1: invalid JSON"],
      })
    );

    expect(error.message).toBe("Could not generate valid output after 3 attempts");
    expect(error.details).toEqual(["call 1: invalid JSON"]);
  });
});
