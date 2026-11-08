import { createContext } from "react";
import type { GenerationResponse } from "../types";

export interface GenerationContextType {
  requirement: string;
  setRequirement: (value: string) => void;
  results: GenerationResponse | null;
  setResults: (value: GenerationResponse | null) => void;
}

export const GenerationContext =
  createContext<GenerationContextType | undefined>(undefined);