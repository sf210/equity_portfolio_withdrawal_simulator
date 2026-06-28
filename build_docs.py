#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Render the project's Markdown docs to HTML and/or PDF.

Markdown -> HTML uses python-markdown (toc/tables/fenced_code) wrapped in the
project print stylesheet; HTML -> PDF prints that with headless Chromium (the
same Skia/PDF path the committed PDFs were made with). The temporary HTML is
written into the doc's own directory so relative images (doc_*.png) resolve.

Usage:
    python build_docs.py METHODOLOGY.md --pdf
    python build_docs.py README.md --html
    python build_docs.py METHODOLOGY.md motivation.md FIT.md --pdf
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import tempfile

import markdown

CSS = """
@page { size: letter; margin: 2cm; }
body { font-family: 'Liberation Sans', Arial, sans-serif; font-size: 11pt;
       line-height: 1.45; color: #1a1a1a; }
h1 { font-size: 22pt; border-bottom: 2px solid #ccc; padding-bottom: 4px; }
h2 { font-size: 16pt; border-bottom: 1px solid #ddd; padding-bottom: 3px;
     margin-top: 24px; }
h3 { font-size: 13pt; margin-top: 18px; }
h4 { font-size: 11.5pt; margin-top: 14px; }
code { font-family: 'Liberation Mono', 'Courier New', monospace; font-size: 9.5pt;
       background: #f3f3f3; padding: 1px 4px; border-radius: 3px; }
pre { background: #f3f3f3; padding: 10px 12px; border-radius: 4px;
      border: 1px solid #e0e0e0; overflow-x: auto; }
pre code { background: none; padding: 0; font-size: 9pt; }
img { max-width: 100%; height: auto; border: 1px solid #ccc; }
a { color: #1a5fb4; text-decoration: none; }
blockquote { border-left: 4px solid #ddd; margin-left: 0; padding-left: 12px;
             color: #444; }
strong { color: #000; }
table { border-collapse: collapse; margin: 10px 0; }
th, td { border: 1px solid #ccc; padding: 4px 8px; font-size: 10pt; }
th { background: #f3f3f3; }
"""

_TMPL = ("<!DOCTYPE html>\n<html><head><meta charset='utf-8'><style>{css}"
         "</style></head><body>\n{body}\n</body></html>\n")


def render_html(md_path: pathlib.Path) -> str:
    text = md_path.read_text(encoding="utf-8")
    body = markdown.markdown(text, extensions=["toc", "tables", "fenced_code"])
    return _TMPL.format(css=CSS, body=body)


def _chromium() -> str:
    for name in ("chromium", "chromium-browser", "google-chrome",
                 "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit("No chromium/chrome found for PDF rendering.")


def write_pdf(md_path: pathlib.Path, html: str) -> pathlib.Path:
    md_path = md_path.resolve()  # Chromium needs an absolute file:// URI
    out = md_path.with_suffix(".pdf")
    tmp_html = md_path.with_name(md_path.stem + ".__build__.html")
    tmp_html.write_text(html, encoding="utf-8")
    with tempfile.TemporaryDirectory() as profile:
        try:
            subprocess.run(
                [_chromium(), "--headless=new", "--disable-gpu", "--no-sandbox",
                 f"--user-data-dir={profile}", "--no-pdf-header-footer",
                 "--run-all-compositor-stages-before-draw",
                 "--virtual-time-budget=15000",
                 f"--print-to-pdf={out}", tmp_html.as_uri()],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            tmp_html.unlink(missing_ok=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docs", nargs="+", help="Markdown file(s) to render")
    ap.add_argument("--html", action="store_true", help="write <name>.html")
    ap.add_argument("--pdf", action="store_true", help="write <name>.pdf")
    args = ap.parse_args()
    if not (args.html or args.pdf):
        ap.error("choose --html and/or --pdf")

    for doc in args.docs:
        md = pathlib.Path(doc)
        html = render_html(md)
        if args.html:
            out = md.with_suffix(".html")
            out.write_text(html, encoding="utf-8")
            print(f"wrote {out}")
        if args.pdf:
            print(f"wrote {write_pdf(md, html)}")


if __name__ == "__main__":
    main()
