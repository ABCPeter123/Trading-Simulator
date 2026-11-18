/** Verify localhost Vite development never asks for the Vercel password.
 * Run against the test Vite dev server with VITE_CLOUD_FRONTEND=1 deliberately,
 * to catch accidental inheritance from a hosted-build environment.
 *
 * Only independently synthetic/mocked API fixtures are used.
 */
import {chromium} from "playwright";

const base="http://127.0.0.1:5173";
const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});
const failures=[];
try {
  for(const width of [390,1440]){
    const context=await browser.newContext({viewport:{width,height:840}});
    const page=await context.newPage();
    const requests=[];
    page.on("request",request=>{
      if(request.url().includes("/api/auth/"))requests.push(request.url());
    });
    page.on("pageerror",error=>failures.push("JS runtime error: "+error.message));
    // Avoid contacting a private local backend or personal market providers
    // during this test. Deliberately return 503 to exercise offline startup.
    await page.route("http://127.0.0.1:5173/api/**",async route=>{
      await route.fulfill({
        status:503,contentType:"application/json",
        body:JSON.stringify({detail:"Offline synthetic development test"}),
      });
    });
    await page.goto(base,{waitUntil:"domcontentloaded"});
    await page.getByRole("navigation",{name:"Application sections"}).waitFor({timeout:15000});
    if(await page.getByLabel("Access password").count()){
      failures.push("Unexpected password field in local dev at "+width+"px");
    }
    if(await page.getByRole("heading",{name:"Your trading research. Your data."}).count()){
      failures.push("Cloud gateway rendered in local dev at "+width+"px");
    }
    if(requests.length){
      failures.push("Local dev tried to use private bridge authentication: "+requests.join(", "));
    }
    await page.getByRole("navigation",{name:"Research Workspaces"}).getByRole("button",{name:"Optimization & Discovery"}).click();
    await page.getByText("Portfolio research, multi-asset").first().waitFor({timeout:15000});
    await context.close();
    console.log("Local passwordless development smoke passed at "+width+"px");
  }
} finally {await browser.close();}
if(failures.length){console.error(failures.join("\n"));process.exitCode=1;}
