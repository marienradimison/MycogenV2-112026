"""Génération de PDF fidèles (fiche paillasse, compte rendu) via Edge/Chrome en mode headless.

Aucun service Internet n'est utilisé : la page est rendue localement à partir des fichiers
statiques du projet (polices Creato Display, CSS d'impression).
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
]


class PdfError(RuntimeError):
    pass


def browser_path():
    custom = os.environ.get("PDF_BROWSER")
    for path in ([custom] if custom else []) + BROWSERS:
        if path and Path(path).is_file():
            return path
    return None


def static_root():
    for d in getattr(settings, "STATICFILES_DIRS", []):
        if Path(d).is_dir():
            return Path(d)
    return Path(settings.STATIC_ROOT)


def asset_base(pdf):
    """Préfixe des fichiers statiques : URL web pour l'aperçu, chemin local pour le PDF."""
    if pdf:
        return static_root().resolve().as_uri() + "/"
    return "/" + settings.STATIC_URL.lstrip("/")


def html_to_pdf(html, timeout=60):
    exe = browser_path()
    if not exe:
        raise PdfError("Aucun navigateur Edge/Chrome trouvé pour générer le PDF.")
    tmp = Path(tempfile.mkdtemp(prefix="mycogen-pdf-"))
    try:
        src, out = tmp / "doc.html", tmp / "doc.pdf"
        src.write_text(html, encoding="utf-8")
        cmd = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               "--no-pdf-header-footer", "--allow-file-access-from-files", "--virtual-time-budget=4000",
               f"--user-data-dir={tmp / 'profile'}", f"--print-to-pdf={out}", src.as_uri()]
        try:
            subprocess.run(cmd, timeout=timeout, capture_output=True, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise PdfError("Délai dépassé pendant la génération du PDF.") from exc
        if not out.is_file() or out.stat().st_size == 0:
            raise PdfError("Le navigateur n'a pas produit de PDF.")
        return out.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def render_document(request, template, context, filename):
    """?format=pdf → PDF téléchargé ; sinon page HTML imprimable."""
    want_pdf = request.GET.get("format") == "pdf"
    html = render_to_string(template, {**context, "PDF": want_pdf, "ASSET": asset_base(want_pdf)}, request)
    if not want_pdf:
        return HttpResponse(html)
    try:
        data = html_to_pdf(html)
    except PdfError as exc:
        html = render_to_string(template, {**context, "PDF": False, "ASSET": asset_base(False),
                                           "pdf_error": str(exc)}, request)
        return HttpResponse(html)
    resp = HttpResponse(data, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
