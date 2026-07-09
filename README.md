# ReasonableRedactor

Local PDF redaction that runs in your browser. Add a PDF, choose what to remove
(emails, phone numbers, postcodes, case and claim numbers, National Insurance
numbers, dates of birth, financial amounts, legislation references, and named
witnesses, companies or terms), and get back a redacted copy. The text is
genuinely removed from the document, not just covered with a black box, and the
tool re-reads its own output to confirm nothing survived.

Your files are processed on your own device and are never uploaded.

Built on [MuPDF](https://mupdf.readthedocs.io/) compiled to WebAssembly, by
[The Reasonable Adjustment](https://thereasonableadjustment.co.uk/).

## Two editions

**Offline edition** (`dist/reasonableredactor-offline.html`) is a single file
with the redaction engine embedded. It makes no network connection at all: its
Content-Security-Policy sets `connect-src 'none'`, so the browser itself blocks
the page from reaching the internet. You can prove it: open the file,
disconnect from the internet, and redact a document. It works. This is the
edition for sensitive or privileged material (client files, medical records,
anything confidential). It is about 13 MB because the engine is inside it.

**Hosted edition** (`src/reasonableredactor-hosted.html`) is a small page (about
40 KB) that loads the engine from a CDN on first visit. Redaction still happens
in the browser and files are still never uploaded; its CSP permits the page to
fetch only the engine and to make no other connection. This is the edition for
everyday, non-sensitive redaction, served from a website.

Both editions share the same redaction code. The offline file is generated from
the hosted file, so the two cannot drift apart.

## Build

Requires Node.js.

```
npm install                 # installs mupdf@1.28.0, the only dependency
npm run build               # regenerates dist/reasonableredactor-offline.html
npm run hash                # prints the SHA-256 of the built offline file
```

`npm run build` reads `src/reasonableredactor-hosted.html`, inlines the MuPDF
engine (JavaScript plus the WebAssembly binary as base64), swaps in the
no-network CSP and the offline wording, and writes the single-file offline
edition to `dist/`.

Edit the tool in `src/reasonableredactor-hosted.html` only. The offline file in
`dist/` is generated; do not edit it by hand. After any change to patterns,
toggles or wording, run `npm run build` so both editions stay in step.

## Hosting the web version

Serve `src/reasonableredactor-hosted.html` as a static file from your site.
Nothing else is required; it fetches the engine from jsDelivr.

To remove the third-party CDN and self-host the engine on your own domain:

1. `npm pack mupdf@1.28.0` (or download from npmjs.com/package/mupdf)
2. Put `dist/mupdf.js`, `dist/mupdf-wasm.js` and `dist/mupdf-wasm.wasm` from the
   package into a `mupdf/` folder beside the HTML file.
3. In the HTML, set `MUPDF_URL` to `./mupdf/mupdf.js`.
4. In the CSP, replace the two `https://cdn.jsdelivr.net` entries with `'self'`.

## Offering the download

Link to the offline file from your hosted page for anyone handling confidential
documents. Serve it from your own domain with a `download` attribute so a click
saves it rather than opening it live:

```html
<a href="/tools/reasonableredactor-offline.html" download>
  Download the offline edition
</a>
```

The SHA-256 of the offline file is in `dist/SHA256SUMS.txt`. Publish it next to
the download so people can confirm the file was not altered in transit. A
downloader checks their copy with `certutil -hashfile FILE SHA256` on Windows,
or `shasum -a 256 FILE` on macOS or Linux, and compares the result.

If you later edit the tool and rebuild, the offline file changes and so does its
hash. Run `npm run hash` and update `dist/SHA256SUMS.txt`.

If you distribute the offline file through GitHub instead, attach it to a
Release as an asset rather than linking a raw file, and do not serve it through
GitHub Pages (that would turn it into a live hosted page).

## Before relying on a redacted document

- Open the "What was removed" log under each file and check it. You are
  responsible for what stays in.
- Scanned pages that are pure images have no text layer and cannot be redacted;
  the tool warns you when it finds them. Run OCR first.
- Automatic patterns are aids, not guarantees. Unusual formats (a case number
  split across two lines, a name not on your list) will be missed. The built-in
  check confirms that whatever the tool did remove is genuinely gone from the
  text layer.

## Licence

AGPL-3.0-or-later. MuPDF is AGPL, so this project is too. If you run the hosted
edition as a network service, you must offer its source to users; the "Source
code" link in the page footer satisfies this. See `LICENSE`.
