/** Public locator only. Never receives or stores trading data or passwords.
 * The owner updates this tiny endpoint pointer whenever the private tunnel starts.
 * The config read token stays server-side in Vercel, never in browser JS.
 */
export default async function handler(req,res){
  res.setHeader("Cache-Control","private, no-store, max-age=0");
  res.setHeader("Referrer-Policy","no-referrer");
  res.setHeader("Access-Control-Allow-Origin","https://trading-simulator-pp-48b0.vercel.app");
  if(req.method!=="GET")return res.status(405).json({error:"Method not allowed"});
  const id=process.env.TRADING_SIM_BRIDGE_CONFIG_ID;
  const token=process.env.TRADING_SIM_BRIDGE_CONFIG_TOKEN;
  if(!id||!token)return res.status(503).json({online:false,error:"Connection directory is not configured."});
  try{
    const data=await fetch("https://edge-config.vercel.com/"+encodeURIComponent(id)+"/item/bridge",{
      headers:{Authorization:"Bearer "+token},signal:AbortSignal.timeout(5000),cache:"no-store"
    });
    if(!data.ok)return res.status(503).json({online:false,error:"Connection directory unavailable."});
    const item=await data.json();
    const url=typeof item?.url==="string"?item.url:"";
    const parsed=new URL(url);
    if(parsed.protocol!=="https:"||parsed.username||parsed.password||parsed.search||parsed.hash||
      parsed.pathname!=="/"||!parsed.hostname.endsWith(".trycloudflare.com"))
      return res.status(503).json({online:false,error:"The private engine has not registered a tunnel."});
    return res.status(200).json({online:true,url:parsed.origin});
  }catch{return res.status(503).json({online:false,error:"The private engine has not registered a tunnel."});}
}
