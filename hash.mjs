// Prints the SHA-256 of the built offline file, to publish beside the download
// so anyone can confirm the file they received is the one you built.
import { createHash } from "crypto";
import { readFileSync } from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const f = path.join(ROOT, "dist", "reasonableredactor-offline.html");
const h = createHash("sha256").update(readFileSync(f)).digest("hex");
console.log(`SHA-256  ${h}  ${path.relative(ROOT, f)}`);
