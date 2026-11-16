import { request } from "./api";

export type AIProvider = "ollama" | "openai" | "off";
export type AIMode = "single" | "portfolio";
export interface AIStatus {
  provider: AIProvider;
  model: string;
  configured: boolean;
  ready: boolean;
  remote: boolean;
  description: string;
}
export interface AIMessage {
  role: "user" | "assistant";
  content: string;
}
export interface AIAnswer {
  answer: string;
  proposed_strategy: string | null;
  proposal_validated: boolean;
  warning: string | null;
  provider: AIProvider;
  model: string;
  applied: false;
  scope: string;
}
export const getAIStatus = () => request<AIStatus>("/ai/status");
export const askAI = (mode: AIMode, runId: string, question: string, history: AIMessage[]) =>
  request<AIAnswer>("/ai/ask", {
    method: "POST",
    body: JSON.stringify({mode, run_id: runId, question, history: history.slice(-6)}),
  });
