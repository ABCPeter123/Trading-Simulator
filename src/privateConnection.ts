/** Connection credentials exist only in the current browser tab's JS memory.
 * They are never shipped in the Vercel bundle or persisted in localStorage.
 */
export const cloudFrontend = import.meta.env.VITE_CLOUD_FRONTEND === "1";
let connection: {origin:string;token:string}|null = null;

export function hasPrivateConnection() { return !!connection; }
export function disconnectPrivateEngine() { connection = null; }

export function apiUrl(route: string): string {
  if (!route.startsWith("/api/")) throw new Error("Invalid API route.");
  if (!cloudFrontend) return route;
  if (!connection) throw new Error("Private trading engine is not connected.");
  return connection.origin + route;
}

export function privateRequestHeaders(extra?: HeadersInit) {
  const headers = new Headers(extra);
  if (cloudFrontend && connection) headers.set("Authorization", "Bearer " + connection.token);
  return headers;
}

export async function connectPrivateEngine(endpoint: string, token: string): Promise<string> {
  if (!cloudFrontend) throw new Error("Private connection applies only to cloud frontend.");
  let url: URL;
  try { url = new URL(endpoint.trim()); } catch { throw new Error("Enter a valid HTTPS tunnel URL."); }
  if (url.username || url.password || url.search || url.hash || url.pathname !== "/" ||
      (url.protocol !== "https:" && !(url.protocol === "http:" &&
      (url.hostname === "127.0.0.1" || url.hostname === "localhost")))) {
    throw new Error("Use a bare HTTPS origin, or HTTP localhost on your own PC.");
  }
  if (token.length < 48) throw new Error("Enter the 48+ character private engine access token.");
  // Validate credentials before enabling the full application.
  const result = await fetch(url.origin + "/api/health", {
    headers: {"Authorization":"Bearer " + token},
    cache:"no-store",
    signal:AbortSignal.timeout(12000),
  });
  if (!result.ok) throw new Error(result.status === 401 ? "Invalid access token." :
    "Private engine refused the connection (" + result.status + ").");
  const data:unknown = await result.json();
  if (!data || typeof data !== "object" || !("mode" in data) ||
      data.mode !== "private-bridge") {
    throw new Error("Target is not an authorized private Trading Simulator engine.");
  }
  connection = {origin:url.origin,token};
  return url.origin;
}
