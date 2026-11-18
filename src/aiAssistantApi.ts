import { request } from "./api";
import { apiUrl, cloudFrontend, privateRequestHeaders } from "./privateConnection";

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
  metrics?: {
    total_ms: number;
    first_output_ms: number | null;
    prompt_tokens: number | null;
    completion_tokens: number | null;
    prompt_ms?: number | null;
    generation_ms?: number | null;
    prompt_tokens_per_second?: number | null;
    generation_tokens_per_second?: number | null;
    reused_prompt_tokens?: number | null;
    new_prompt_tokens?: number | null;
  };
}
export const getAIStatus = (model?: string) => request<AIStatus>(`/ai/status${model ? `?model=${encodeURIComponent(model)}` : ""}`);
export const warmupAI = () => request<{started:boolean;reason:string}>("/ai/warmup",{method:"POST"});
export const askAI = (mode: AIMode, runId: string, question: string, history: AIMessage[], language: "en"|"zh-CN" = "en", model?: string) =>
  request<AIAnswer>("/ai/ask", {
    method: "POST",
    body: JSON.stringify({mode, run_id: runId, question, history: history.slice(-6), language, ...(model ? {model} : {})}),
  });


export interface AIStreamProgress {
  phase: "waiting" | "generating";
  preview: string;
  output_characters?: number;
  first_output_ms?: number | null;
}

/**
 * SSE over authenticated fetch instead of EventSource. This supports POST
 * history in the request body, the private bridge's bearer authorization,
 * AbortController cancellation, and real-time local Qwen4B progress.
 */
export async function askAIStream(
  mode: AIMode, runId: string, question: string, history: AIMessage[],
  language: "en" | "zh-CN", model: string | undefined,
  signal: AbortSignal, onProgress: (progress: AIStreamProgress) => void,
): Promise<AIAnswer> {
  const response = await fetch(apiUrl("/api/ai/ask/stream"), {
    method: "POST",
    headers: privateRequestHeaders({
      "Content-Type": "application/json",
      "Accept": "text/event-stream",
    }),
    body: JSON.stringify({
      mode, run_id: runId, question, history: history.slice(-6), language,
      ...(model ? {model} : {}),
    }),
    cache: cloudFrontend ? "no-store" : "no-store",
    signal,
  });
  if (!response.ok || !response.body) {
    // HTTP validation errors arrive as ordinary JSON before streaming begins.
    let message = "Local AI stream is unavailable.";
    try {
      const payload: unknown = await response.json();
      if (payload && typeof payload === "object" && "detail" in payload &&
          typeof payload.detail === "string") {
        message = payload.detail;
      }
    } catch { /* use the fixed non-sensitive message */ }
    throw new Error(message);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: AIAnswer | null = null;
  let finished = false;
  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done) {finished = true; break;}
      buffer += decoder.decode(value, {stream: true});
      buffer = buffer.replace(/\r\n/g, "\n");
      if (buffer.length > 262144) throw new Error("AI stream exceeded the safe response limit.");
      let separator = buffer.indexOf("\n\n");
      while (separator !== -1) {
        const block = buffer.slice(0, separator);
        buffer = buffer.slice(separator + 2);
        const event = block.split("\n").find(line=>line.startsWith("event:"))?.slice(6).trim();
        const raw = block.split("\n").filter(line=>line.startsWith("data:"))
          .map(line=>line.slice(5).trimStart()).join("\n");
        if (event && raw) {
          let packet: unknown;
          try { packet = JSON.parse(raw); } catch { packet = null; }
          if (packet && typeof packet === "object") {
            const payload = packet as Record<string, unknown>;
            if (event === "status") onProgress({phase:"waiting",preview:""});
            if (event === "progress") {
              onProgress({
                phase:"generating",
                preview:typeof payload.preview === "string" ? payload.preview : "",
                output_characters:typeof payload.output_characters === "number"
                  ? payload.output_characters : undefined,
                first_output_ms:typeof payload.first_output_ms === "number"
                  ? payload.first_output_ms : null,
              });
            }
            if (event === "error") throw new Error(
              typeof payload.message === "string" ? payload.message : "AI stream failed.");
            if (event === "done") {
              if (typeof payload.answer !== "string" || payload.applied !== false)
                throw new Error("Invalid local AI completion.");
              result = packet as AIAnswer;
            }
          }
        }
        separator = buffer.indexOf("\n\n");
      }
    }
    if (!result) throw new Error("Local AI stream ended before a validated response.");
    return result;
  } finally {
    // On abort, malformed JSON or upstream errors, close the HTTP stream
    // promptly instead of leaving llama.cpp decoding an unused response.
    if (!finished) await reader.cancel().catch(()=>{});
    reader.releaseLock();
  }
}
