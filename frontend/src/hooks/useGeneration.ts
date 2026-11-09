import { useContext } from "react";
import { GenerationContext } from "../context/GenerationContext";

// Reads the shared generation state. Fails loudly if the provider is missing.
export function useGeneration() {
  const context = useContext(GenerationContext);

  if (!context) {
    throw new Error("useGeneration must be used inside GenerationProvider");
  }

  return context;
}