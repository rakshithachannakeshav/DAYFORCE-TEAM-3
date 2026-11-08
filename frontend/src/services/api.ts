import axios from "axios";
import type { BackendGenerationResult, GenerationResponse } from "../types";
import { buildRequirementInput, toGenerationResponse } from "./adapter";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// A local model is slow. The backend's worst case is 3 generation attempts plus
// 3 supplement rounds at about 305 s each, so the browser must not give up first.
const REQUEST_TIMEOUT_MS = 6 * 305 * 1000;

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: REQUEST_TIMEOUT_MS,
});

export class GenerationError extends Error {
  details: string[];

  constructor(message: string, details: string[] = []) {
    super(message);
    this.name = "GenerationError";
    this.details = details;
  }
}

// Pipeline errors are {message, details}; FastAPI request validation errors are
// {detail: [{loc, msg}]}. Both can arrive with a 422.
function readErrorBody(data: unknown): { message?: string; details: string[] } {
  if (!data || typeof data !== "object") {
    return { details: [] };
  }

  const body = data as {
    message?: unknown;
    details?: unknown;
    detail?: unknown;
  };

  if (Array.isArray(body.detail)) {
    const details = body.detail.map((item: { loc?: unknown[]; msg?: string }) =>
      [item.loc?.join("."), item.msg].filter(Boolean).join(": ")
    );
    return { details };
  }

  return {
    message: typeof body.message === "string" ? body.message : undefined,
    details: Array.isArray(body.details) ? body.details.map(String) : [],
  };
}

export function toGenerationError(error: unknown): GenerationError {
  if (!axios.isAxiosError(error)) {
    return new GenerationError("Something went wrong while generating tests.");
  }

  if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") {
    return new GenerationError(
      "The request timed out before the backend answered. Try a shorter requirement or check the backend logs."
    );
  }

  if (!error.response) {
    return new GenerationError(
      `Cannot reach the backend at ${API_BASE_URL}. Is it running? Start it with: uvicorn backend.main:app --port 8000`
    );
  }

  const { message, details } = readErrorBody(error.response.data);

  switch (error.response.status) {
    case 422:
      return new GenerationError(
        "The requirement was rejected. Please correct it and try again.",
        details
      );
    case 502:
      return new GenerationError(
        message ?? "The model did not produce a valid result. Please try again.",
        details
      );
    case 503:
      // The backend's message names the fix: `ollama serve` or `ollama pull <model>`.
      return new GenerationError(
        message ?? "The local model is unavailable. Check that Ollama is running.",
        details
      );
    case 504:
      return new GenerationError(
        message ?? "The model took too long to respond. Please try again.",
        details
      );
    default:
      return new GenerationError(
        message ?? `The backend returned an unexpected error (HTTP ${error.response.status}).`,
        details
      );
  }
}

export const generateTests = async (
  requirement: string,
  signal?: AbortSignal
): Promise<GenerationResponse> => {
  if (import.meta.env.VITE_USE_MOCK === "true") {
    const { mockResults } = await import("../data/mockResults");
    return toGenerationResponse(mockResults);
  }

  try {
    const response = await api.post<BackendGenerationResult>(
      "/api/llm/generate",
      buildRequirementInput(requirement),
      { signal }
    );

    return toGenerationResponse(response.data);
  } catch (error) {
    if (axios.isCancel(error)) {
      throw error;
    }
    throw toGenerationError(error);
  }
};
