import { request } from "./api";

export type AIProvider = "ollama" | "llama_cpp" | "openai" | "off";
export type AIMode = "single" | "portfolio";
export interface AIStatus {
  provider: AIProvider;
  model: string;
  available_models?: string[];
  configured: boolean;
  ready: boolean;
  remote: boolean;
  warming?: boolean;
  loaded?: boolean;
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
export const getAIStatus = (model?: string) => request<AIStatus>(`/ai/status${model ? `?model=${encodeURIComponent(model)}` : ""}`);
export const warmupAI = () => request<{started:boolean;reason:string}>("/ai/warmup",{method:"POST"});
export const askAI = (mode: AIMode, runId: string, question: string, history: AIMessage[], language: "en"|"zh-CN" = "en", model?: string) =>
  request<AIAnswer>("/ai/ask", {
    method: "POST",
    body: JSON.stringify({mode, run_id: runId, question, history: history.slice(-6), language, ...(model ? {model} : {})}),
  });
