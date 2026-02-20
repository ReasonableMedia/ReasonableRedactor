import os
import re
import time
import tempfile
import fitz  # PyMuPDF
import gradio as gr

APP_NAME = "ReasonableRedactor"

# ── Regex patterns ─────────────────────────────────────────────────────────────

HEADER_KEYS = (
    "to:", "cc:", "bcc:", "from:", "subject:", "date:", "sent:", "reply-to:", "attachments:"
)

EMAIL_CORE = r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}"
TOKEN_EMAIL_RE = re.compile(
    r"(?i)(?P<prefix><)?(?P<email>" + EMAIL_CORE + r")(?P<suffix>>)?(?P<trail>[,.;:]?)"
)

# Phone: UK landline/mobile, international with country code, various separators
PHONE_RE = re.compile(
    r"(?<!\w)"
    r"("
    r"(\+44|0044)[\s\-.]?\(?\d{2,5}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"
    r"|0\(?\d{3,5}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"
    r"|\(\d{3,5}\)[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"
    r"|\+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"
    r")"
    r"(?!\w)"
)

COMMON_WORDS = {
    "the","and","for","are","but","not","you","all","any","can","had","her",
    "was","one","our","out","day","get","has","him","his","how","its","let",
    "man","new","now","old","see","two","way","who","boy","did","put","say",
    "she","too","use","may","re","mr","mrs","ms","dr","dear","kind","from",
    "with","this","that","have","been","will","your","they","what","when",
    "here","just","know","take","into","year","good","much","some","time",
    "very","even","back","only","come","its","also","after","think","more",
}

# ── Core helpers ───────────────────────────────────────────────────────────────

def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

def _line_text(line):
    return "".join(span.get("text", "") for span in line.get("spans", []))

def _colors(style):
    if style == "blackout":
        return (0, 0, 0), (1, 1, 1)
    return (1, 1, 1), (0, 0, 0)

def _add_redaction(page, rect, style, text=None, fontsize=9):
    fill, text_color = _colors(style)
    if text is None:
        page.add_redact_annot(rect, fill=fill)
    else:
        page.add_redact_annot(rect, text=text, fill=fill,
                               text_color=text_color, fontsize=fontsize)

def _collect_bcc_line_bboxes(page):
    d = page.get_text("dict")
    bboxes = []
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = block.get("lines", [])
        i = 0
        while i < len(lines):
            raw = _line_text(lines[i])
            norm = _norm(raw)
            if norm.startswith("bcc:"):
                x0, y0, x1, y1 = lines[i]["bbox"]
                bboxes.append(fitz.Rect(x0, y0, x1, y1))
                j = i + 1
                while j < len(lines):
                    nxt_norm = _norm(_line_text(lines[j]))
                    if any(nxt_norm.startswith(k) for k in HEADER_KEYS):
                        break
                    x0, y0, x1, y1 = lines[j]["bbox"]
                    bboxes.append(fitz.Rect(x0, y0, x1, y1))
                    j += 1
                i = j
                continue
            i += 1
    return bboxes

def _rect_overlaps_any(rect, rects):
    return any(rect.intersects(r) for r in rects)

def _mask_email_keep_domain(mask_user, email):
    user, domain = email.split("@", 1)
    return f"{mask_user}@{domain}"

def _should_mask_email(cfg, email):
    e = email.lower()
    if e in {x.lower() for x in cfg["keep_emails"]}:
        return False
    domain = e.split("@", 1)[1] if "@" in e else ""
    if domain in {x.lower() for x in cfg["keep_domains"]}:
        return False
    if cfg["mask_scope"] == "personal":
        return e in {x.lower() for x in cfg["personal_emails"]}
    return True

# ── Per-page redaction ─────────────────────────────────────────────────────────

def redact_bcc_in_page(page, cfg):
    bboxes = _collect_bcc_line_bboxes(page)
    if not bboxes:
        return 0
    _add_redaction(page, bboxes[0], cfg["style"], text=cfg["bcc_replacement"], fontsize=9)
    for rr in bboxes[1:]:
        _add_redaction(page, rr, cfg["style"], text=None)
    return len(bboxes)

def mask_emails_in_page(page, cfg):
    words = page.get_text("words") or []
    if not words:
        return 0
    bcc_regions = _collect_bcc_line_bboxes(page) if cfg["skip_email_mask_inside_bcc"] else []
    redactions = 0
    for w in words:
        x0, y0, x1, y1, token = w[0], w[1], w[2], w[3], w[4]
        if not token or "@" not in token:
            continue
        rr = fitz.Rect(x0, y0, x1, y1)
        if bcc_regions and _rect_overlaps_any(rr, bcc_regions):
            continue
        m = TOKEN_EMAIL_RE.search(token)
        if not m:
            continue
        email = m.group("email")
        if not _should_mask_email(cfg, email):
            continue
        masked = _mask_email_keep_domain(cfg["mask_user"], email)
        prefix = m.group("prefix") or ""
        suffix = m.group("suffix") or ""
        trail  = m.group("trail") or ""
        replacement = f"{prefix}{masked}{suffix}{trail}"
        pad = 0.6
        rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        _add_redaction(page, rect, cfg["style"], text=replacement, fontsize=9)
        redactions += 1
    return redactions

def mask_phones_in_page(page, cfg):
    blocks = page.get_text("dict").get("blocks", [])
    redactions = 0
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text:
                    continue
                for m in PHONE_RE.finditer(text):
                    x0s, y0s, x1s, y1s = span["bbox"]
                    span_w = x1s - x0s
                    char_w = span_w / max(len(text), 1)
                    cx0 = x0s + m.start() * char_w
                    cx1 = x0s + m.end()   * char_w
                    pad = 0.6
                    rect = fitz.Rect(cx0 - pad, y0s - pad, cx1 + pad, y1s + pad)
                    _add_redaction(page, rect, cfg["style"],
                                   text="[number redacted]", fontsize=9)
                    redactions += 1
    return redactions

def mask_names_in_page(page, cfg):
    if not cfg.get("names"):
        return 0
    patterns = []
    for name in sorted(cfg["names"], key=len, reverse=True):
        escaped = re.escape(name.strip())
        patterns.append((name, re.compile(rf"(?i)\b{escaped}\b")))

    blocks = page.get_text("dict").get("blocks", [])
    redactions = 0
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text:
                    continue
                x0s, y0s, x1s, y1s = span["bbox"]
                span_w = x1s - x0s
                char_w = span_w / max(len(text), 1)
                for name, pat in patterns:
                    for m in pat.finditer(text):
                        cx0 = x0s + m.start() * char_w
                        cx1 = x0s + m.end()   * char_w
                        pad = 0.6
                        rect = fitz.Rect(cx0 - pad, y0s - pad, cx1 + pad, y1s + pad)
                        _add_redaction(page, rect, cfg["style"],
                                       text="[name redacted]", fontsize=9)
                        redactions += 1
    return redactions

def redact_one(in_path, out_path, cfg):
    doc   = fitz.open(in_path)
    hits  = 0
    pages = 0
    for page in doc:
        page_hits = 0
        page_hits += redact_bcc_in_page(page, cfg)
        page_hits += mask_emails_in_page(page, cfg)
        if cfg.get("redact_phones"):
            page_hits += mask_phones_in_page(page, cfg)
        if cfg.get("redact_names") and cfg.get("names"):
            page_hits += mask_names_in_page(page, cfg)
        if page_hits:
            pages += 1
            hits  += page_hits
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc.save(out_path, deflate=True, garbage=4)
    doc.close()
    return hits, pages

# ── Validation ─────────────────────────────────────────────────────────────────

def parse_list(s):
    if not s or not s.strip():
        return []
    return [x.strip() for x in re.split(r"[,\n]", s) if x.strip()]

def validate_names(raw_names):
    """Returns (cleaned_names, warnings, errors)."""
    if not raw_names or not raw_names.strip():
        return [], [], []

    entries  = parse_list(raw_names)
    cleaned  = []
    warnings = []
    errors   = []

    for entry in entries:
        name = re.sub(r"^['\"\s]+|['\"\s]+$", "", entry)
        if not name:
            continue

        if len(name) < 3:
            errors.append(
                f"'{name}' is too short (minimum 3 characters) — "
                "short names match too many things accidentally."
            )
            continue

        if name.lower() in COMMON_WORDS:
            errors.append(
                f"'{name}' is a very common word and would redact far too much of the document. "
                "Use a full name instead, e.g. 'Alice Day' rather than just 'Day'."
            )
            continue

        if not re.search(r"[A-Za-z]", name):
            errors.append(f"'{name}' doesn't look like a name — it contains no letters.")
            continue

        if len(name.split()) == 1 and len(name) < 6:
            warnings.append(
                f"'{name}' is a single short word — it will be redacted every time it appears "
                "anywhere in the document. Consider using a full name to be more precise."
            )

        cleaned.append(name)

    # Deduplicate
    seen = set()
    deduped = []
    for n in cleaned:
        key = n.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(n)
        else:
            warnings.append(f"'{n}' appears more than once — duplicates ignored.")

    return deduped, warnings, errors

def validate_and_preview(raw_names):
    """Live feedback shown as the user types."""
    if not raw_names or not raw_names.strip():
        return ""
    names, warnings, errors = validate_names(raw_names)
    lines = []
    for e in errors:
        lines.append(f"❌  {e}")
    for w in warnings:
        lines.append(f"⚠️  {w}")
    if names:
        preview = ", ".join(f'"{n}"' for n in names[:8])
        if len(names) > 8:
            preview += f" … and {len(names) - 8} more"
        lines.append(f"✅  Will redact: {preview}")
    return "\n".join(lines)

# ── Gradio handler ─────────────────────────────────────────────────────────────

def run_redaction(
    files, style, mask_scope, personal_emails,
    keep_emails, keep_domains, mask_user, bcc_replacement,
    skip_email_mask_inside_bcc, redact_phones, redact_names, raw_names,
):
    if not files:
        return [], "⚠️ No files uploaded."

    names, name_warnings, name_errors = (
        validate_names(raw_names) if redact_names else ([], [], [])
    )
    if name_errors:
        return [], "❌ Please fix these issues before running:\n\n" + "\n".join(name_errors)

    cfg = {
        "style":                      "blackout" if style == "Blackout" else "clean",
        "mask_scope":                 "personal" if mask_scope == "Specific emails only" else "all",
        "personal_emails":            parse_list(personal_emails),
        "keep_emails":                parse_list(keep_emails),
        "keep_domains":               parse_list(keep_domains),
        "mask_user":                  mask_user.strip() or "[redacted]",
        "bcc_replacement":            bcc_replacement.strip() or "Bcc: [redacted]",
        "skip_email_mask_inside_bcc": skip_email_mask_inside_bcc,
        "redact_phones":              redact_phones,
        "redact_names":               redact_names,
        "names":                      names,
    }

    stamp         = time.strftime("%Y%m%d-%H%M%S")
    tmp_dir       = tempfile.mkdtemp()
    output_files  = []
    log_lines     = [f"⚠️  {w}" for w in name_warnings]

    for file in files:
        in_path  = file.name
        base     = os.path.splitext(os.path.basename(in_path))[0]
        out_path = os.path.join(tmp_dir, f"{base}-redacted-{stamp}.pdf")
        try:
            hits, pages = redact_one(in_path, out_path, cfg)
            output_files.append(out_path)
            log_lines.append(f"✅ {base}.pdf — {hits} redaction(s) across {pages} page(s)")
        except Exception as e:
            log_lines.append(f"❌ {base}.pdf — Error: {e}")

    return output_files, "\n".join(log_lines)

# ── UI ─────────────────────────────────────────────────────────────────────────

css = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap');

body, .gradio-container {
    background-color: #111108 !important;
    color: #f0e8d0 !important;
    font-family: 'DM Sans', system-ui, sans-serif !important;
    font-size: 15px !important;
}

#tra-header {
    text-align: center;
    padding: 24px 0 16px;
    border-bottom: 1px solid #c9a84c44;
    margin-bottom: 8px;
}
#tra-header h2 {
    font-size: 20px !important;
    font-weight: 600 !important;
    color: #c9a84c !important;
    letter-spacing: 0.04em !important;
    margin: 0 0 6px 0 !important;
}
#tra-header p {
    font-size: 14px !important;
    color: #a89060 !important;
    margin: 0 !important;
}
#tra-footer {
    text-align: center;
    padding: 20px 0 8px;
    border-top: 1px solid #c9a84c33;
    margin-top: 8px;
    font-size: 13px;
    color: #7a6840;
}
#tra-footer a {
    color: #c9a84c;
    text-decoration: none;
}
#tra-footer a:hover { text-decoration: underline; }

/* Bigger, readable body text everywhere */
.gr-markdown p, .gr-markdown li,
span[class*="description"], .info,
label span, .svelte-1f354aw {
    font-size: 14px !important;
    line-height: 1.5 !important;
    color: #f0e8d0 !important;
}

/* Block backgrounds */
.gr-group, div[class*="block"] {
    background-color: #1c1c12 !important;
    border-color: #2e2c1a !important;
}

/* Input fields */
input, textarea, select {
    background-color: #141410 !important;
    border-color: #2e2c1a !important;
    color: #f0e8d0 !important;
    font-size: 14px !important;
    font-family: 'DM Sans', system-ui, sans-serif !important;
}
input:focus, textarea:focus {
    border-color: #c9a84c !important;
    box-shadow: 0 0 0 2px #c9a84c22 !important;
}

/* Labels */
label {
    font-size: 14px !important;
    font-weight: 500 !important;
    color: #c9a84c !important;
}

/* Primary button */
button.primary, button[variant="primary"] {
    background-color: #c9a84c !important;
    color: #111108 !important;
    font-size: 15px !important;
    font-weight: 600 !important;
    border: none !important;
}
button.primary:hover, button[variant="primary"]:hover {
    background-color: #debb5e !important;
}

/* Secondary buttons */
button.secondary, button[variant="secondary"] {
    border-color: #c9a84c !important;
    color: #c9a84c !important;
    background: transparent !important;
    font-size: 14px !important;
}

/* Checkboxes and radios */
input[type="checkbox"], input[type="radio"] {
    accent-color: #c9a84c;
}

/* Log output */
.output-log textarea, .name-preview textarea {
    font-family: 'Courier New', monospace !important;
    font-size: 13px !important;
    background: #141410 !important;
    color: #c9a84c !important;
    border-color: #2e2c1a !important;
    line-height: 1.6 !important;
}

/* Section headings */
.gr-markdown h3 { color: #c9a84c !important; font-size: 15px !important; font-weight: 600 !important; }
.gr-markdown strong { color: #f0e8d0 !important; }

/* Accordion */
details > summary {
    font-size: 14px !important;
    color: #c9a84c !important;
    background: #1c1c12 !important;
    border-color: #2e2c1a !important;
}

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #111108; }
::-webkit-scrollbar-thumb { background: #2e2c1a; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #c9a84c; }
"""

tra_theme = gr.themes.Base(
    primary_hue=gr.themes.Color(
        c50="#fdf8ec", c100="#f7edcc", c200="#edd98a", c300="#e0bf5a",
        c400="#c9a84c", c500="#b8953d", c600="#9a7a2e", c700="#7a5e20",
        c800="#5a4415", c900="#3a2c0d", c950="#1a1408",
    ),
    secondary_hue=gr.themes.Color(
        c50="#f5f2e8", c100="#e8e0c8", c200="#cfc0a0", c300="#b8a07a",
        c400="#9a8c6a", c500="#7a6e50", c600="#5a5038", c700="#3a3420",
        c800="#2a2418", c900="#1c1c12", c950="#111108",
    ),
    neutral_hue=gr.themes.Color(
        c50="#f5f2e8", c100="#e8e0c8", c200="#cfc0a0", c300="#b8a07a",
        c400="#9a8c6a", c500="#7a6e50", c600="#5a5038", c700="#3a3420",
        c800="#2a2418", c900="#1c1c12", c950="#111108",
    ),
    font=gr.themes.GoogleFont("DM Sans"),
    font_mono="Courier New",
    text_size=gr.themes.sizes.text_md,
).set(
    body_background_fill="#111108",
    body_text_color="#f0e8d0",
    block_background_fill="#1c1c12",
    block_border_color="#2e2c1a",
    block_label_text_color="#c9a84c",
    block_title_text_color="#c9a84c",
    input_background_fill="#141410",
    input_border_color="#2e2c1a",
    input_placeholder_color="#5a5038",
    checkbox_background_color="#141410",
    checkbox_border_color="#c9a84c",
    button_primary_background_fill="#c9a84c",
    button_primary_background_fill_hover="#debb5e",
    button_primary_text_color="#111108",
    button_secondary_background_fill="transparent",
    button_secondary_border_color="#c9a84c",
    button_secondary_text_color="#c9a84c",
    accordion_text_color="#c9a84c",
)

with gr.Blocks(title="ReasonableRedactor", theme=tra_theme, css=css) as demo:

    gr.HTML("""
    <div id="tra-header">
        <h2>ReasonableRedactor</h2>
        <p>Redact personal data from PDFs. Everything runs locally on your computer. Nothing is uploaded anywhere.</p>
    </div>
    """)

    with gr.Row():

        # ── Left column ────────────────────────────────────────────────────────
        with gr.Column(scale=3):
            file_input = gr.File(
                label="📂 Drop PDFs here (or click to browse)",
                file_types=[".pdf"],
                file_count="multiple",
            )

            run_btn = gr.Button("🔍 Redact PDFs", variant="primary", size="lg")

            file_output = gr.File(
                label="📥 Download redacted PDFs",
                file_count="multiple",
                interactive=False,
            )

            log_output = gr.Textbox(
                label="Log",
                lines=7,
                interactive=False,
                elem_classes=["output-log"],
                placeholder="Results will appear here after processing.",
            )

        # ── Right column ───────────────────────────────────────────────────────
        with gr.Column(scale=2):
            gr.Markdown("### ⚙️ What to redact")

            # Emails
            with gr.Group():
                gr.Markdown("**📧 Email addresses** *(always on)*")
                gr.Markdown(
                    "<small>Usernames replaced with [redacted], domain kept. "
                    "Example: alice@nhs.uk becomes [redacted]@nhs.uk</small>"
                )
                mask_scope = gr.Radio(
                    choices=["All emails", "Specific emails only"],
                    value="All emails",
                    label="Which emails?",
                )
                personal_emails = gr.Textbox(
                    label="Emails to redact",
                    placeholder="alice@example.com\nbob@example.com",
                    info="One per line, or comma-separated.",
                    lines=3,
                    visible=False,
                )

            # Phones
            with gr.Group():
                gr.Markdown("**📞 Phone numbers**")
                redact_phones = gr.Checkbox(
                    label="Redact phone numbers",
                    value=False,
                    info="Detects UK formats (01xxx, 07xxx, +44) and common international formats.",
                )

            # Names
            with gr.Group():
                gr.Markdown("**👤 Names**")
                redact_names = gr.Checkbox(
                    label="Redact specific names",
                    value=False,
                    info="Provide a list and the tool will find and remove them wherever they appear.",
                )
                names_box = gr.Textbox(
                    label="Names to redact",
                    placeholder="Alice Day\nBob Smith\nDr Carol White",
                    info="One name per line. Use the name as it appears in the document.",
                    lines=4,
                    visible=False,
                )
                name_preview = gr.Textbox(
                    label="Name validation",
                    interactive=False,
                    lines=3,
                    visible=False,
                    elem_classes=["name-preview"],
                )

            # Advanced
            with gr.Accordion("Advanced options", open=False):
                style = gr.Radio(
                    choices=["Clean", "Blackout"],
                    value="Clean",
                    label="Redaction style",
                    info="Clean: white box blends in. Blackout: solid black bars.",
                )
                mask_user = gr.Textbox(
                    label="Email username replacement",
                    value="[redacted]",
                )
                keep_emails = gr.Textbox(
                    label="Emails to always keep visible",
                    placeholder="info@organisation.com",
                    info="These exact addresses will never be masked. Comma-separated.",
                )
                keep_domains = gr.Textbox(
                    label="Domains to always keep visible",
                    placeholder="nhs.uk, gov.uk",
                    info="All addresses at these domains will be left untouched.",
                )
                bcc_replacement = gr.Textbox(
                    label="Bcc header replacement text",
                    value="Bcc: [redacted]",
                )
                skip_bcc_mask = gr.Checkbox(
                    label="Skip email masking inside Bcc area",
                    value=True,
                    info="Avoids double-processing addresses already covered by the Bcc redaction.",
                )

    gr.HTML("""
    <div id="tra-footer">
        A free tool by <a href="https://www.thereasonableadjustment.co.uk" target="_blank">The Reasonable Adjustment</a>
        &nbsp;&middot;&nbsp;
        AI assistant powered by <a href="https://ki-ki.co.uk" target="_blank">Ki-Ki.co.uk</a>
        &nbsp;&middot;&nbsp;
        Runs entirely on your computer. No data is sent anywhere.
    </div>
    """)

    mask_scope.change(
        fn=lambda s: gr.update(visible=(s == "Specific emails only")),
        inputs=mask_scope,
        outputs=personal_emails,
    )

    redact_names.change(
        fn=lambda checked: (gr.update(visible=checked), gr.update(visible=checked)),
        inputs=redact_names,
        outputs=[names_box, name_preview],
    )

    names_box.change(
        fn=validate_and_preview,
        inputs=names_box,
        outputs=name_preview,
    )

    run_btn.click(
        fn=run_redaction,
        inputs=[
            file_input, style, mask_scope, personal_emails,
            keep_emails, keep_domains, mask_user, bcc_replacement,
            skip_bcc_mask, redact_phones, redact_names, names_box,
        ],
        outputs=[file_output, log_output],
    )

if __name__ == "__main__":
    demo.launch(inbrowser=True)
