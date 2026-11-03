"""Génère docs/GUIDE_MYCOGEN.pdf à partir de docs/GUIDE_MYCOGEN.md (mise en page MYCOGEN, via Edge).

    .venv\\Scripts\\python docs\\build_guide_pdf.py

Nécessite le paquet « markdown » (pip install markdown).
"""
import pathlib
import subprocess
import sys
import tempfile

import markdown

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "GUIDE_MYCOGEN.md"
OUT = ROOT / "docs" / "GUIDE_MYCOGEN.pdf"
STATIC = (ROOT / "static").as_uri()
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

CSS = f"""
@font-face {{ font-family: "Creato Display"; src: url("{STATIC}/fonts/CreatoDisplay-Regular.otf"); font-weight: 400; }}
@font-face {{ font-family: "Creato Display"; src: url("{STATIC}/fonts/CreatoDisplay-Medium.otf"); font-weight: 500; }}
@font-face {{ font-family: "Creato Display"; src: url("{STATIC}/fonts/CreatoDisplay-Bold.otf"); font-weight: 700; }}
@font-face {{ font-family: "Creato Display"; src: url("{STATIC}/fonts/CreatoDisplay-ExtraBold.otf"); font-weight: 800; }}
@page {{ size: A4; margin: 16mm 15mm 16mm; }}
body {{ font-family: "Creato Display", "Segoe UI", sans-serif; font-size: 9.6pt; color: #1f2d33; line-height: 1.45; }}
.cover {{ background: #12303a; color: #fff; padding: 22mm 14mm 16mm; margin: -16mm -15mm 10mm; position: relative;
  background-image: linear-gradient(90deg, rgba(18,48,58,.97), rgba(18,48,58,.9)), url("{STATIC}/img/aloalo-pattern.svg");
  background-size: auto, 220px auto; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
.cover img {{ height: 64px; vertical-align: middle; }}
.cover .name {{ font-size: 34pt; font-weight: 800; letter-spacing: .07em; display: inline-block; vertical-align: middle; margin-left: 10px; }}
.cover .sub {{ color: #6eafc4; font-size: 12pt; margin-top: 6px; }}
.cover .title {{ font-size: 17pt; font-weight: 700; margin-top: 18mm; }}
.cover .meta {{ font-size: 9pt; color: #c9dde4; margin-top: 4px; }}
h1 {{ display: none; }}
h2 {{ font-size: 14pt; color: #12303a; border-bottom: 2px solid #6eafc4; padding-bottom: 3px; margin-top: 18px;
  break-after: avoid; }}
h2:not(:first-of-type) {{ break-before: page; }}
h3 {{ font-size: 11pt; color: #3f8197; margin: 14px 0 6px; break-after: avoid; }}
table {{ border-collapse: collapse; width: 100%; margin: 6px 0 10px; font-size: 8.6pt; }}
tr {{ break-inside: avoid; }} thead {{ display: table-header-group; }}
th {{ background: #eef3f5; text-align: left; font-weight: 700; color: #12303a; }}
th, td {{ border: 1px solid #d7e1e5; padding: 4px 6px; vertical-align: top; }}
code {{ font-family: Consolas, monospace; font-size: 8.4pt; background: #f1f5f7; padding: 1px 4px; border-radius: 3px; }}
pre {{ background: #12303a; color: #e8f1f4; padding: 8px 10px; border-radius: 6px; font-size: 8.2pt;
  white-space: pre-wrap; break-inside: avoid; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
pre code {{ background: none; color: inherit; padding: 0; }}
blockquote {{ border-left: 4px solid #e8a33d; background: #fff8ea; margin: 8px 0; padding: 6px 10px;
  -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
blockquote p {{ margin: 0; }}
a {{ color: #2f6f85; text-decoration: none; }}
ul, ol {{ padding-left: 18px; }} li {{ margin: 2px 0; }}
hr {{ border: 0; border-top: 1px solid #d7e1e5; margin: 12px 0; }}
"""


def main():
    text = SRC.read_text(encoding="utf-8")
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "toc", "sane_lists"])
    body = body.replace("[ ]", "☐").replace("[x]", "☑")
    cover = f"""<div class="cover"><img src="{STATIC}/img/Mycogene_logo_monochrome_white.png" alt="">
      <span class="name">MYCOGEN</span>
      <div class="sub">Unité des Mycobactéries · Centre National de Référence des Mycobactéries<br>Institut Pasteur de Madagascar</div>
      <div class="title">Guide de référence et suivi du projet</div>
      <div class="meta">LIMS de l'Unité des Mycobactéries — document interne</div></div>"""
    html = f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><style>{CSS}</style></head><body>{cover}{body}</body></html>'
    with tempfile.TemporaryDirectory() as tmp:
        page = pathlib.Path(tmp) / "guide.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=5000",
                        "--allow-file-access-from-files", f"--user-data-dir={pathlib.Path(tmp) / 'p'}",
                        f"--print-to-pdf={OUT}", page.as_uri()], timeout=120, check=False)
    print(OUT if OUT.exists() else "échec", file=sys.stdout)


if __name__ == "__main__":
    main()
