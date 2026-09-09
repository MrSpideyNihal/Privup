/* Emit a Verdict as JSON from the JavaScript core, for parity testing.
 *
 *   node tools/js_verdict.mjs <tag_set> [--html] < policy.txt
 *
 * The Python test suite runs this against every fixture and compares the
 * result field for field with the Python pipeline. A JS change that alters a
 * verdict fails the Python tests, which is the only thing that keeps two
 * implementations of the same logic from drifting apart.
 */

import { run, verdictToDict } from "../extension/src/core/main.js";

const args = process.argv.slice(2);
const tagSet = args.find((a) => !a.startsWith("--"));
const asHtml = args.includes("--html");

if (!tagSet) {
  process.stderr.write("usage: node tools/js_verdict.mjs <tag_set> [--html] < text\n");
  process.exit(2);
}

let text = "";
for await (const chunk of process.stdin) text += chunk;

try {
  const verdict = run({
    text,
    tagSet,
    origin: "raw_text",
    contentType: asHtml ? "text/html" : "text/plain",
  });
  process.stdout.write(JSON.stringify(verdictToDict(verdict)));
} catch (error) {
  process.stderr.write(`${error.name}: ${error.message}\n`);
  process.exit(1);
}
