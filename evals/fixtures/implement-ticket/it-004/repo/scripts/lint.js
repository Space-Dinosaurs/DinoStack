// Minimal custom lint: reject any src/*.ts that contains an unused `_tmp` variable.
const fs = require("fs");
const path = require("path");
const srcDir = path.join(__dirname, "..", "src");
let bad = false;
for (const f of fs.readdirSync(srcDir)) {
  if (!f.endsWith(".ts")) continue;
  const text = fs.readFileSync(path.join(srcDir, f), "utf8");
  if (/\b_tmp\b/.test(text)) {
    console.error(`[lint] ${f}: scratch variable _tmp is banned.`);
    bad = true;
  }
}
if (bad) process.exit(1);
console.log("lint-ok");
