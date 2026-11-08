
import type { GenerationResponse } from "../types";

export const mockResults: GenerationResponse = {
  status: "ready",

  acceptance_criteria: [
    {
      id: "AC01",
      description: "Users can log in with valid email and password."
    },
    {
      id: "AC02",
      description: "Invalid login credentials must be rejected."
    },
    {
      id: "AC03",
      description: "Authenticated users can securely log out."
    }
  ],

  test_scenarios: [
    {
      id: "TC01",
      criterion_id: "AC01",
      scenario: "Login using valid credentials",
      expected_result: "User is authenticated successfully",
      type: "positive"
    },
    {
      id: "TC02",
      criterion_id: "AC02",
      scenario: "Login using incorrect password",
      expected_result: "Authentication is rejected",
      type: "negative"
    },
    {
      id: "TC03",
      criterion_id: "AC02",
      scenario: "Login with an unregistered email",
      expected_result: "Authentication is rejected",
      type: "negative"
    },
    {
      id: "TC04",
      criterion_id: "AC03",
      scenario: "Log out of an active session",
      expected_result: "Session is terminated",
      type: "positive"
    }
  ],

  edge_cases: [
    "Login with empty email or password",
    "Login with an invalid email format",
    "Attempt to reuse a session after logout"
  ],

  ambiguities: [
    "The requirement does not specify account lockout behavior."
  ],

  clarification_questions: [
    "Should accounts be locked after repeated failed login attempts?"
  ]
};