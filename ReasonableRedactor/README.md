# ReasonableRedactor

A small local tool that redacts **Bcc** and masks **email usernames** in PDFs while keeping the domain.

Examples:
- `A.Day@npa.co.uk` becomes `[redacted]@npa.co.uk`
- `Bcc: alice@example.com, bob@example.com` becomes `Bcc: [redacted]` and any wrapped continuation lines are removed

This keeps documents readable while removing personal identifiers.

## Safety and privacy

- Your PDFs stay on your computer.
- Nothing is uploaded anywhere.
- The tool reads PDFs from the `in` folder and writes new PDFs to the `out` folder.

## What you need

- Windows 10 or Windows 11
- Python 3.10+ installed

If you do not have Python installed:
1. Go to the official Python site and install it.
2. During install, tick "Add Python to PATH".

## Quick start (easy way)

1. Put your PDFs into the `in` folder.
2. Double click `RUN.bat`.
3. When asked "Edit settings?", type `y` if you want to change defaults.
4. Get the redacted PDFs from the `out` folder.

## Quick start (Command Prompt method)

1. Open Command Prompt:
   - Press the Windows key
   - Type `cmd`
   - Press Enter

2. Go to the folder where you extracted this tool.
   Example:
   ```
   cd /d "C:\Tools\ReasonableRedactor"
   ```

3. Install requirements:
   ```
   py -m pip install -r requirements.txt
   ```

4. Run:
   ```
   py src\reasonableredactor.py
   ```

## Settings (simple)

When you run the tool, it asks if you want to edit settings.

You can choose:
- Clean style (recommended), it blends into the page with no big black bars
- Blackout style, it uses black boxes with white replacement text

You can also choose:
- Mask all email addresses (recommended for publishing PDFs)
- Or mask only a personal list

You can keep certain addresses visible (optional):
- Keep emails, example: `advocacy@thereasonableadjustment.co.uk`
- Keep domains, example: `thereasonableadjustment.co.uk`

Your settings are saved into `config.json`.

## Notes

- This performs real PDF redactions using PyMuPDF redaction annotations and applies them.
- Some PDFs contain text as images. In that case, text masking may not catch everything.
