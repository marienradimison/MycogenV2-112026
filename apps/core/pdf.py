"""Génération de PDF fidèles (fiche paillasse, compte rendu) via Edge/Chrome en mode headless.

Aucun service Internet n'est utilisé : la page est rendue localement à partir des fichiers
statiques du projet (polices Creato Display, CSS d'impression).
"""
import os
import shutil
import subprocess
import tempfile
import time
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
        # Edge peut rendre la main avant d'avoir écrit le fichier : attendre qu'il soit complet
        deadline = time.monotonic() + timeout
        size = -1
        while time.monotonic() < deadline:
            current = out.stat().st_size if out.is_file() else 0
            if current and current == size:
                return out.read_bytes()
            size = current
            time.sleep(0.5)
        raise PdfError("Le navigateur n'a pas produit de PDF.")
    finally:
        remove_dir(tmp)


def remove_dir(path, attempts=10):
    """Edge garde quelques instants son profil verrouillé : réessayer, puis purger les restes plus anciens."""
    for _ in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            break
        time.sleep(0.5)
    limit = time.time() - 600
    for old in path.parent.glob("mycogen-pdf-*"):
        try:
            if old.is_dir() and old.stat().st_mtime < limit:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass


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
