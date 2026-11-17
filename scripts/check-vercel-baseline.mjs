// Read-only comparison against the exact Git SHA currently deployed to Vercel.
// This never deploys, resets, stages, commits or checks out any files.
import {readFileSync} from "node:fs";
import {execFileSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {dirname,resolve} from "node:path";

const root=resolve(dirname(fileURLToPath(import.meta.url)),"..");
const config=JSON.parse(readFileSync(resolve(root,"config/production-baseline.json"),"utf8"));
const sha=config.deployed_commit;
if(!/^[a-f0-9]{40}$/.test(sha))throw new Error("Invalid production snapshot SHA");
const git=(args)=>execFileSync("git",args,{cwd:root,encoding:"utf8",stdio:["ignore","pipe","pipe"]}).trim();
const head=git(["rev-parse","HEAD"]);
const branch=git(["branch","--show-current"])||"(detached)";
const releaseConfig=JSON.parse(readFileSync(resolve(root,"vercel.json"),"utf8"));
console.log("Actual deployed Vercel source:",sha);
console.log("Current development source:   ",head,"["+branch+"]");
console.log("Production deployment URL:    ",config.deployment_url);
console.log("Automatic Vercel Git deploys: ",releaseConfig.git?.deploymentEnabled===false?"DISABLED":"NOT DISABLED");
if(releaseConfig.git?.deploymentEnabled!==false){
  console.error("ERROR: Development must not automatically deploy to Vercel.");
  process.exitCode=1;
}
try {
  git(["cat-file","-e",sha+"^{commit}"]);
  try {
    git(["merge-base","--is-ancestor",sha,head]);
    console.log("Development includes live source baseline: YES");
  } catch {
    console.error("ERROR: Development branch does not contain the pinned live production commit.");
    process.exitCode=1;
  }
  const changed=git(["diff","--name-only",sha,head,"--","src","package.json","vite.config.ts","public"]);
  const files=changed?changed.split(/\r?\n/):[];
  console.log("Frontend files changed since live release:",files.length);
  for(const file of files)console.log("  "+file);
  console.log("Local baseline: .\\scripts\\start-vercel-baseline.ps1 (serves deployed commit separately)");
  console.log("Local development: .\\start-local.ps1 (serves HEAD; never resets existing improvements)");
} catch {
  console.log("Pinned commit not found in local Git history. Run 'git fetch origin main' and rerun this command.");
  // No network calls. On shallow CI clones this condition can be expected.
  process.exitCode=2;
}
