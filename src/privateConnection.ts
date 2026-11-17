/** Cloud browser secrets are tab-memory-only. No strategy or session is
 * persisted to Vercel, cookies, localStorage or the JavaScript bundle.
 */
export const cloudFrontend = import.meta.env.VITE_CLOUD_FRONTEND === "1";
let connection: {origin:string;token:string}|null = null;

export function hasPrivateConnection() { return !!connection; }
export function disconnectPrivateEngine() {
  const current=connection;
  connection=null;
  if(current)void fetch(current.origin+"/api/auth/logout",{
    method:"POST",headers:{"Authorization":"Bearer "+current.token},cache:"no-store",
    signal:AbortSignal.timeout(4000),
  }).catch(()=>{});
}

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

export async function connectPrivateEngine(password:string): Promise<void> {
  if (!cloudFrontend) throw new Error("Private connection applies only to cloud frontend.");
  if (!password || password.length>128) throw new Error("Enter your shared web password.");
  // This is a tiny public locator, not a database or a data proxy.
  const lookup=await fetch("/api/bridge-location",{
    cache:"no-store",signal:AbortSignal.timeout(10000),
  }).catch(()=>{throw new Error("Cannot look up your desktop connection.");});
  if (!lookup.ok) throw new Error("Desktop is not connected. Ask the owner to start the private bridge.");
  const locator:unknown=await lookup.json();
  const address=locator && typeof locator==="object" && "url" in locator ? locator.url : null;
  if (typeof address!=="string") throw new Error("Private desktop address is unavailable.");
  let url:URL;
  try {url=new URL(address);} catch{throw new Error("Invalid desktop tunnel address.");}
  if(url.protocol!=="https:"||!url.hostname.endsWith(".trycloudflare.com")||
      url.pathname!=="/"||url.search||url.hash||url.username||url.password)
    throw new Error("Connection directory returned an invalid tunnel.");
  // Password is sent ONLY to the owner's FastAPI instance through HTTPS
  // and Cloudflare. Vercel never receives the plaintext or session token.
  const response=await fetch(url.origin+"/api/auth/login",{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({password}),cache:"no-store",signal:AbortSignal.timeout(12000),
  }).catch(()=>{throw new Error("Your desktop is offline or the private tunnel is unavailable.");});
  if (!response.ok) throw new Error(response.status===401?
    "Incorrect password or too many attempts. Try again later.":
    "Unable to sign in to your desktop ("+response.status+").");
  const result:unknown=await response.json();
  if(!result||typeof result!=="object"||!("token" in result)||
     typeof result.token!=="string"||!("mode" in result)||result.mode!=="private-bridge")
    throw new Error("Unexpected private login response.");
  const health=await fetch(url.origin+"/api/health",{
    headers:{"Authorization":"Bearer "+result.token},
    cache:"no-store",signal:AbortSignal.timeout(8000),
  });
  if(!health.ok)throw new Error("Your secure login session could not be verified.");
  connection={origin:url.origin,token:result.token};
}
