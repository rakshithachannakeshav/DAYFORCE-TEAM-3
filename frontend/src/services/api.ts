import axios from "axios";
import type { GenerationRequest, GenerationResponse } from "../types";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30000,
});

export const generateTests = async (
  data: GenerationRequest
): Promise<GenerationResponse> => {
  const response = await api.post<GenerationResponse>(
    "/generate",
    data
  );

  return response.data;
};