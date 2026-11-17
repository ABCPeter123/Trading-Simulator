/** No real URL, strategy, or credential is used in this test. */
import assert from "node:assert/strict";
import handler from "../api/bridge-location.js";

const originalFetch=globalThis.fetch;
const originalId=process.env.TRADING_SIM_BRIDGE_CONFIG_ID;
const originalToken=process.env.TRADING_SIM_BRIDGE_CONFIG_TOKEN;
function req(method="GET"){return {method};}
function res(){
  return {headers:{},statusCode:200,payload:null,
    setHeader(key,value){this.headers[key.toLowerCase()]=value;return this;},
    status(n){this.statusCode=n;return this;},
    json(p){this.payload=p;return this;}};
}
try{
  process.env.TRADING_SIM_BRIDGE_CONFIG_ID="ecfg_testfixture";
  process.env.TRADING_SIM_BRIDGE_CONFIG_TOKEN="synthetic-directory-test-token";
  let called=false;
  globalThis.fetch=async (url,options)=>{
    called=true;
    assert.match(url,/edge-config\.vercel\.com\/ecfg_testfixture\/item\/bridge/);
    assert.equal(options.headers.Authorization,"Bearer synthetic-directory-test-token");
    return {ok:true,json:async()=>({url:"https://synthetic-example.trycloudflare.com",
      strategy_code:"never publish this",password:"not shared"})};
  };
  let reply=res();await handler(req(),reply);
  assert.equal(reply.statusCode,200);
  assert.deepEqual(reply.payload,{online:true,url:"https://synthetic-example.trycloudflare.com"});
  assert.equal(reply.headers["cache-control"],"private, no-store, max-age=0");
  assert.ok(called);
  globalThis.fetch=async()=>({ok:true,json:async()=>({url:"https://attacker.example"})});
  reply=res();await handler(req(),reply);
  assert.equal(reply.statusCode,503);
  reply=res();await handler(req("POST"),reply);
  assert.equal(reply.statusCode,405);
  console.log("Vercel tunnel locator only publishes validated endpoint; no strategy data");
} finally {
  globalThis.fetch=originalFetch;
  if(originalId===undefined)delete process.env.TRADING_SIM_BRIDGE_CONFIG_ID;
  else process.env.TRADING_SIM_BRIDGE_CONFIG_ID=originalId;
  if(originalToken===undefined)delete process.env.TRADING_SIM_BRIDGE_CONFIG_TOKEN;
  else process.env.TRADING_SIM_BRIDGE_CONFIG_TOKEN=originalToken;
}
