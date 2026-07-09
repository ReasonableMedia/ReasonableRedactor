// Regenerates the offline single-file edition from the hosted source.
//
// It inlines the MuPDF engine (JS glue + wrapper + wasm-as-base64) into one
// self-contained HTML file, and swaps the hosted Content-Security-Policy for
// one that forbids ALL network access (connect-src 'none'), because the
// offline edition needs no network at all.
//
// Usage:
//   npm install            (installs mupdf@1.28.0, the only dependency)
//   node scripts/build-offline.mjs
//
// Output: dist/reasonableredactor-offline.html
//
// Keep the version here in step with the version in src/reasonableredactor-hosted.html.

import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MUPDF_DIST = path.join(ROOT, "node_modules", "mupdf", "dist");
const SRC = path.join(ROOT, "src", "reasonableredactor-hosted.html");
const OUT = path.join(ROOT, "dist", "reasonableredactor-offline.html");

function read(p) { return fs.readFileSync(p, "utf8"); }

// --- 1. build the inlined engine (glue + wrapper + wasm base64) ---
const glue = read(path.join(MUPDF_DIST, "mupdf-wasm.js"));
const wrapper = read(path.join(MUPDF_DIST, "mupdf.js"));

if (!glue.trimEnd().endsWith("export default _;"))
  throw new Error("mupdf-wasm.js export shape changed; update this script.");
const glue2 = glue.replace(/export default _;\s*$/, "globalThis.__mupdf_glue_default = _;\n");

const importLine = 'import libmupdf_wasm from "./mupdf-wasm.js";';
if (!wrapper.includes(importLine))
  throw new Error("mupdf.js import shape changed; update this script.");
const wrapper2 = wrapper.replace(importLine, "const libmupdf_wasm = globalThis.__mupdf_glue_default;");

const ns = "\nconst mupdf = { Document, Matrix, Font, ColorSpace, PDFDocument, PDFPage, Pixmap };\n";
const b64 = fs.readFileSync(path.join(MUPDF_DIST, "mupdf-wasm.wasm")).toString("base64");
const preamble = `
const __wasmBytes = Uint8Array.from(atob(${JSON.stringify(b64)}), c => c.charCodeAt(0));
globalThis["$libmupdf_wasm_Module"] = { wasmBinary: __wasmBytes };
`;
const engine =
  "// ===== Inlined MuPDF engine (AGPL, Artifex). WASM embedded as base64; nothing is fetched. =====\n"
  + preamble + "\n" + glue2 + "\n" + wrapper2 + ns;

// --- 2. take the hosted app script, drop the CDN loader, prepend the engine ---
const hosted = read(SRC);
const scriptMatch = hosted.match(/<script type="module">([\s\S]*?)<\/script>/);
if (!scriptMatch) throw new Error("could not find the module script in the hosted source.");
let app = scriptMatch[1];
app = app.replace(/const MUPDF_URL = .*;\n/, "");
app = app.replace(/let mupdf = null;\n/, "");
app = app.replace(
  /\(async \(\) => \{[\s\S]*?\}\)\(\);\n/,
  'statusEl.textContent = "Ready. Add PDFs above. Working fully offline.";\n'
);
const moduleBody = engine + "\n// ===== ReasonableRedactor application =====\n" + app;

// --- 3. rebuild the HTML: strict no-network CSP, offline-appropriate text ---
let out = hosted.replace(scriptMatch[0], '<script type="module">\n' + moduleBody + '\n</script>');

// swap the hosted CSP (allows the CDN) for the offline CSP (allows no network)
out = out.replace(
  /<meta http-equiv="Content-Security-Policy"[^>]*>/,
  `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'unsafe-inline'; img-src blob: data:; font-src data:; worker-src blob:; child-src blob:; connect-src 'none'; base-uri 'none'; form-action 'none'">`
);

// replace the header comment with the offline one
out = out.replace(/<!--[\s\S]*?-->/, `<!--
  ReasonableRedactor (offline edition) - GENERATED FILE, do not edit by hand.
  Built from src/reasonableredactor-hosted.html by scripts/build-offline.mjs.

  Runs entirely from this one file. There is no download at runtime and no
  server: the MuPDF engine is compiled to WebAssembly and embedded here as
  base64. A Content-Security-Policy sets connect-src 'none', so the browser
  itself forbids this page from opening any network connection. Open it,
  disconnect from the internet, redact a PDF: it works, and nothing can leave.

  Engine: MuPDF (mupdf.js, AGPL-3.0, by Artifex). This file is AGPL.
-->`);

// swap the hosted safety card for the offline one (verifiable no-network claims)
const cardStart = out.indexOf('<div class="card safety">');
const cardEnd = out.indexOf('<div class="card" id="settingsCard">');
if (cardStart === -1 || cardEnd === -1) throw new Error("could not locate the safety card to swap.");
const offlineCard = `<div class="card safety">
    <h2>Is this safe? How your documents stay private</h2>
    <p class="lead">This tool cannot send your files anywhere. Here is why, in plain terms, and how to confirm it yourself without taking anyone's word for it.</p>

    <p>You are not visiting a website. This is a single file that lives on your own computer, like a PDF or a Word document. It opens inside your browser only because a browser is the program that knows how to display it. Once you have the file, it does not need the internet to work.</p>

    <p>There is nowhere for your document to go. When an ordinary website handles a file, it sends that file to a computer somewhere else, owned by whoever runs the site. This tool has no such computer behind it. The part that does the actual redaction is built into this one file. When you add a PDF, it is opened only in your computer's short-term memory, edited there, and handed straight back to you. It is never sent out, because there is no outside address to send it to.</p>

    <p>The browser is instructed to block all internet access while this file is open. The file carries a standard browser security rule (a Content Security Policy) that your browser follows automatically. It forbids this page from making any internet connection at all. So even if the file were somehow tampered with, the browser itself would refuse to let anything leave. It is a locked door the browser enforces, not a promise you have to trust.</p>

    <p>Nothing is kept afterwards. A redacted copy is created only when you click Download, and it saves wherever you choose, like any other download. Close the tab and the file you loaded, along with everything the tool was working on, is wiped from memory. There is no account, no history, and no stored copy of your documents anywhere.</p>

    <p>What this does not cover, in fairness. This stops your documents being uploaded or retained. It cannot protect a computer that is already compromised by other software, and it cannot judge what you do with the redacted file afterwards. Redaction is also only as thorough as the options you choose, so always open the finished PDF and check it. Everything the tool removed is listed under \u201cWhat was removed\u201d on each file for exactly that reason.</p>

    <details>
      <summary>Three ways to check this yourself</summary>
      <ol>
        <li>Disconnect from the internet (turn off wi-fi or unplug the cable), then redact a document. It still works. A tool that relied on the internet could not do that.</li>
        <li>Open your browser's developer tools and choose the Network tab, then redact a file. You will see no data leaving. This is the check an IT department would run.</li>
        <li>This file is plain text. Open it in Notepad or TextEdit and search for <code>connect-src 'none'</code>. That single line is the instruction that tells the browser to block all network access.</li>
      </ol>
    </details>
  </div>

  `;
out = out.slice(0, cardStart) + offlineCard + out.slice(cardEnd);

// offline edition is a file, not a hosted page: adjust the two badges/wording
out = out.replace(
  '<span class="badge local">✓ Your files are redacted in your browser and never uploaded</span>',
  '<span class="badge local">✓ Runs entirely on your device — files never leave it</span>');
out = out.replace(
  '<span class="badge real">Real redaction — text is removed, not covered</span>',
  '<span class="badge real">Real redaction — text is removed, not covered</span>\n      <span class="badge real">Offline file — the browser is blocked from any network</span>');
out = out.replace("Loading redaction engine…", "Starting redaction engine (embedded, no download)…");

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, out);
const mb = (Buffer.byteLength(out) / 1048576).toFixed(1);
console.log(`Built ${path.relative(ROOT, OUT)} (${mb} MB)`);
