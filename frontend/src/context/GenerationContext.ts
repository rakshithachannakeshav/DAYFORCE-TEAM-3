import { createContext } from "react";
import type { GenerationResponse } from "../types";

// The submitted requirement and its results, shared between pages.
// Held in memory only, so refreshing the page clears them.
export interface GenerationContextType {
  requirement: string;
  setRequirement: (value: string) => void;
  results: GenerationResponse | null;
  setResults: (value: GenerationResponse | null) => void;
}

export const GenerationContext =
  createContext<GenerationContextType | undefined>(undefined);