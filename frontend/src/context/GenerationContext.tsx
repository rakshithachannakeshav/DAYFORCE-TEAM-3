import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import type { GenerationResponse } from "../types";

interface GenerationContextType {
  requirement: string;
  setRequirement: (value: string) => void;
  results: GenerationResponse | null;
  setResults: (value: GenerationResponse | null) => void;
}

const GenerationContext = createContext<GenerationContextType | undefined>(
  undefined
);

export function GenerationProvider({ children }: { children: ReactNode }) {
  const [requirement, setRequirement] = useState("");
  const [results, setResults] = useState<GenerationResponse | null>(null);

  return (
    <GenerationContext.Provider
      value={{ requirement, setRequirement, results, setResults }}
    >
      {children}
    </GenerationContext.Provider>
  );
}

export function useGeneration() {
  const context = useContext(GenerationContext);

  if (!context) {
    throw new Error("useGeneration must be used inside GenerationProvider");
  }

  return context;
}