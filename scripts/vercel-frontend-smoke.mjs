/** Vercel mode smoke test. All market data is synthetic and API mocked. */
import { chromium } from "playwright";

const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
const site="http://127.0.0.1:4173";
const remote="https://synthetic-fixture.trycloudflare.com";
const token="x".repeat(64);
const password="synthetic-private-password";
const failures=[];
try {
  for(const width of [390,1440]){
    const context=await browser.newContext({viewport:{width,height:900}});
    const page=await context.newPage();
    page.on("pageerror",e=>failures.push("Runtime error: "+e.message));
    const before=[];
    page.on("request",r=>{if(r.url().includes("/api/"))before.push(r.url());});
    await page.goto(site,{waitUntil:"domcontentloaded"});
    await page.getByRole("heading",{name:"Your trading research. Your data."}).waitFor();
    await page.waitForTimeout(500);
    if(before.length)failures.push("Vercel frontend contacted an API before private authorization: "+before);
    const loaded=await page.locator("[data-loaded-bars]").first().getAttribute("data-loaded-bars");
    if(Number(loaded)!==450)failures.push("Synthetic preview chart did not load 450 bars at width "+width+": "+loaded);
    await page.route(site+"/api/bridge-location",async route=>{
      await route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({online:true,url:remote})});
    });
    await page.route(remote+"/api/**",async route=>{
      const req=route.request();
      if(req.method()==="OPTIONS"){
        await route.fulfill({status:200,headers:{
          "Access-Control-Allow-Origin":site,"Access-Control-Allow-Headers":"authorization,content-type",
          "Access-Control-Allow-Methods":"GET,POST,PUT,DELETE,OPTIONS",
          "Access-Control-Allow-Private-Network":"true",
        },body:"OK"});
      } else {
        if(!req.url().endsWith("/api/auth/login")&&req.headers()["authorization"]!=="Bearer "+token) failures.push("Missing bearer token for "+req.url());
        const path=new URL(req.url()).pathname;
        let payload={};
        if(path==="/api/auth/login"){
          const reqbody=JSON.parse(req.postData()||"{}");
          if(reqbody.password!==password)failures.push("Password not forwarded to private desktop.");
          payload={mode:"private-bridge",token};
        }
        else if(path==="/api/health")payload={status:"ok",mode:"private-bridge"};
        else if(path==="/api/auth/logout")payload={logged_out:true};
        else if(path==="/api/live/status")payload={worker_online:false,heartbeat_age_seconds:null,heartbeat_at:null,
          active_deployments:0,pending_signals:0,critical_alerts:0,recent_evaluations:[],
          execution_mode:"human_confirmation_only",broker_connected:false};
        else if(["/api/live/deployments","/api/live/signals","/api/live/alerts","/api/strategies",
                 "/api/live/research/runs"].includes(path))payload=[];
        else if(path==="/api/live/journal")payload={fills:[],positions:[],realized_pnl:0,realized_by_currency:{},note:""};
        else if(path==="/api/live/notifications")payload={channels:[],deliveries:[]};
        else if(path==="/api/arcade/runs")payload=[];
        else if(path==="/api/instruments")payload=[];
        else if(path==="/api/account")payload={cash:100000,equity:100000,realized_pnl:0,unrealized_pnl:0,positions:[],fills:[],has_unpriced_positions:false};
        await route.fulfill({status:200,contentType:"application/json",
          headers:{"Access-Control-Allow-Origin":site,"Cache-Control":"no-store"},
          body:JSON.stringify(payload)});
      }
    });
    if(await page.getByLabel("Engine URL").count())failures.push("Manual tunnel field still visible.");
    if(await page.getByLabel("Private access token").count())failures.push("Manual API token field still visible.");
    await page.getByLabel("Access password").fill(password);
    await page.getByRole("button",{name:"Open trading workspace"}).click();
    await page.getByText("Private engine connected. Trading data remains on your PC.").waitFor({timeout:12000});
    const stored=await page.evaluate(()=>Object.fromEntries(Object.entries(localStorage)));
    if(JSON.stringify(stored).includes(token)||JSON.stringify(stored).includes(password))failures.push("Password or private session persisted to localStorage");
    await page.getByRole("button",{name:"Disconnect private engine"}).click();
    await page.getByRole("heading",{name:"Your trading research. Your data."}).waitFor();
    await context.close();
    console.log("Vercel password-only connection smoke passed at "+width+"px");
  }
} finally {await browser.close();}
if(failures.length){console.error(failures.join("\n"));process.exitCode=1;}
