import { useState } from "react";
import type { ReactNode } from "react";
import { GenerationContext } from "./GenerationContext";
import type { GenerationContextType } from "./GenerationContext";

// Owns the generation state and makes it available to every page.
export function GenerationProvider({ children }: { children: ReactNode }) {
  const [requirement, setRequirement] = useState("");
  const [results, setResults] = useState<GenerationContextType["results"]>(null);

  return (
    <GenerationContext.Provider
      value={{ requirement, setRequirement, results, setResults }}
    >
      {children}
    </GenerationContext.Provider>
  );
}