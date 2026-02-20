import os
import re
import time
import json
import fitz  # PyMuPDF

APP_NAME = "ReasonableRedactor"

# -----------------------
# Defaults (safe, no personal data baked in)
# -----------------------
DEFAULTS = {
    "mask_scope": "all",            # "all" or "personal"
    "personal_emails": [],          # used only if mask_scope == "personal"
    "keep_emails": [],              # never mask these exact emails
    "keep_domains": [],             # never mask these domains
    "mask_user": "[redacted]",      # username replacement
    "style": "clean",               # "clean" or "blackout"
    "skip_email_mask_inside_bcc": True,
    "bcc_replacement": "Bcc: [redacted]",
}

HEADER_KEYS = (
    "to:", "cc:", "bcc:", "from:", "subject:", "date:", "sent:", "reply-to:", "attachments:"
)

EMAIL_CORE = r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}"
TOKEN_EMAIL_RE = re.compile(
    r"(?i)(?P<prefix><)?(?P<email>" + EMAIL_CORE + r")(?P<suffix>>)?(?P<trail>[,.;:]?)"
)

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

def _line_text(line) -> str:
    return "".join(span.get("text", "") for span in line.get("spans", []))

def _colors(style: str):
    # Returns (fill, text_color)
    if style == "blackout":
        return (0, 0, 0), (1, 1, 1)  # black fill, white text
    return (1, 1, 1), (0, 0, 0)      # white fill, black text

def _add_redaction(page: fitz.Page, rect: fitz.Rect, style: str, text: str | None = None, fontsize: int = 9) -> None:
    fill, text_color = _colors(style)
    if text is None:
        page.add_redact_annot(rect, fill=fill)
    else:
        page.add_redact_annot(
            rect,
            text=text,
            fill=fill,
            text_color=text_color,
            fontsize=fontsize,
        )

def _collect_bcc_line_bboxes(page: fitz.Page) -> list[fitz.Rect]:
    """
    Returns rectangles covering the Bcc header line and any wrapped continuation lines.
    """
    d = page.get_text("dict")
    bboxes: list[fitz.Rect] = []

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
                    nxt_raw = _line_text(lines[j])
                    nxt_norm = _norm(nxt_raw)
                    if any(nxt_norm.startswith(k) for k in HEADER_KEYS):
                        break

                    x0, y0, x1, y1 = lines[j]["bbox"]
                    bboxes.append(fitz.Rect(x0, y0, x1, y1))
                    j += 1

                i = j
                continue

            i += 1

    return bboxes

def _rect_overlaps_any(rect: fitz.Rect, rects: list[fitz.Rect]) -> bool:
    return any(rect.intersects(r) for r in rects)

def _mask_email_keep_domain(mask_user: str, email: str) -> str:
    user, domain = email.split("@", 1)
    return f"{mask_user}@{domain}"

def _should_mask_email(cfg: dict, email: str) -> bool:
    e = email.lower()
    keep_emails = {x.lower() for x in cfg["keep_emails"]}
    keep_domains = {x.lower() for x in cfg["keep_domains"]}
    if e in keep_emails:
        return False
    domain = e.split("@", 1)[1] if "@" in e else ""
    if domain in keep_domains:
        return False

    if cfg["mask_scope"] == "personal":
        personal = {x.lower() for x in cfg["personal_emails"]}
        return e in personal

    # "all"
    return True

def redact_bcc_in_page(page: fitz.Page, cfg: dict) -> int:
    bboxes = _collect_bcc_line_bboxes(page)
    if not bboxes:
        return 0

    # First line gets replacement text
    _add_redaction(page, bboxes[0], cfg["style"], text=cfg["bcc_replacement"], fontsize=9)

    # Continuation lines get wiped
    for rr in bboxes[1:]:
        _add_redaction(page, rr, cfg["style"], text=None)

    return len(bboxes)

def mask_emails_in_page(page: fitz.Page, cfg: dict) -> int:
    """
    Word-level masking: preserves To/Cc labels, names, commas.
    """
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
        trail = m.group("trail") or ""
        replacement = f"{prefix}{masked}{suffix}{trail}"

        pad = 0.6
        rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        _add_redaction(page, rect, cfg["style"], text=replacement, fontsize=9)
        redactions += 1

    return redactions

def redact_one(in_path: str, out_path: str, cfg: dict) -> tuple[int, int]:
    doc = fitz.open(in_path)
    hits = 0
    pages = 0

    for page in doc:
        page_hits = 0
        page_hits += redact_bcc_in_page(page, cfg)
        page_hits += mask_emails_in_page(page, cfg)

        if page_hits:
            pages += 1
            hits += page_hits
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc.save(out_path, deflate=True, garbage=4)
    doc.close()
    return hits, pages

def _read_cfg(cfg_path: str) -> dict:
    cfg = dict(DEFAULTS)
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                disk = json.load(f)
            for k in DEFAULTS:
                if k in disk:
                    cfg[k] = disk[k]
        except Exception:
            pass
    return cfg

def _write_cfg(cfg_path: str, cfg: dict) -> None:
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

def _prompt_list(label: str) -> list[str]:
    s = input(label).strip()
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]

def interactive_setup(cfg: dict) -> dict:
    print(f"\n=== {APP_NAME} setup ===")
    print("This tool runs locally on your machine. It does not upload files anywhere.\n")

    style = input("Style (1 = clean, 2 = blackout) [1]: ").strip()
    cfg["style"] = "blackout" if style == "2" else "clean"

    scope = input("Mask scope (1 = all emails, 2 = personal list only) [1]: ").strip()
    cfg["mask_scope"] = "personal" if scope == "2" else "all"

    if cfg["mask_scope"] == "personal":
        cfg["personal_emails"] = _prompt_list("Enter personal emails to mask (comma-separated): ")
    else:
        cfg["personal_emails"] = []

    cfg["mask_user"] = input(f"Username replacement [{cfg['mask_user']}]: ").strip() or cfg["mask_user"]

    cfg["keep_emails"] = _prompt_list("Emails to keep visible (comma-separated, optional): ")
    cfg["keep_domains"] = _prompt_list("Domains to keep visible (comma-separated, optional): ")

    bcc_rep = input(f"Bcc replacement text [{cfg['bcc_replacement']}]: ").strip()
    if bcc_rep:
        cfg["bcc_replacement"] = bcc_rep

    skip = input("Skip masking inside Bcc area? (Y/n) [Y]: ").strip().lower()
    cfg["skip_email_mask_inside_bcc"] = False if skip == "n" else True

    print("\nSaved settings will be reused next time.\n")
    return cfg

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(here, ".."))
    in_dir = os.path.join(project_root, "in")
    out_dir = os.path.join(project_root, "out")
    cfg_path = os.path.join(project_root, "config.json")

    os.makedirs(in_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    cfg = _read_cfg(cfg_path)

    edit = input("Edit settings? (y/N) [N] : ").strip().lower()
    if edit == "y":
        cfg = interactive_setup(cfg)
        _write_cfg(cfg_path, cfg)

    pdfs = [f for f in os.listdir(in_dir) if f.lower().endswith(".pdf")]
    if not pdfs:
        print("\nNo PDFs found.")
        print(f"Put PDFs into: {in_dir}")
        return

    stamp = time.strftime("%Y%m%d-%H%M%S")

    print(f"\n== {APP_NAME} processing ==")
    total_hits = 0
    total_pages = 0
    ok = 0
    fail = 0

    for fn in pdfs:
        src = os.path.join(in_dir, fn)
        base, _ = os.path.splitext(fn)
        dst = os.path.join(out_dir, f"{base}-redacted-{stamp}.pdf")

        try:
            hits, pages = redact_one(src, dst, cfg)
            ok += 1
            total_hits += hits
            total_pages += pages
            print(f"OK: {fn} -> {os.path.basename(dst)} | redactions={hits} pages={pages}")
        except Exception as e:
            fail += 1
            print(f"FAIL: {fn} | {e}")

    print("\n== Done ==")
    print(f"Processed: {ok} ok, {fail} failed")
    print(f"Total redactions: {total_hits} across {total_pages} page(s)")
    print(f"Output folder: {out_dir}")

if __name__ == "__main__":
    main()
