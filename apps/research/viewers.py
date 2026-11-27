"""MycoLearn : lecteurs intégrés par format de fichier (tout s'affiche dans MYCOGEN, sans ouvrir d'autre application).

    vidéo, audio, PDF, image          lecteurs natifs du navigateur
    Word (.docx)                      rendu dans la page (docx-preview)
    Excel / tableur / CSV             rendu dans la page, un onglet par feuille (SheetJS)
    Markdown                          rendu dans la page (marked + DOMPurify)
    HTML                              cadre isolé (sandbox : pas d'accès à la session MYCOGEN)
    texte                             affichage brut
    PowerPoint, .doc, .odt, .rtf…     converti en PDF sur le serveur par LibreOffice, puis lecteur PDF
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

VIEWERS = {
    "video": (".mp4", ".webm", ".ogg", ".ogv", ".mov", ".m4v"),
    "audio": (".mp3", ".m4a", ".wav", ".aac", ".oga", ".opus"),
    "pdf": (".pdf",),
    "image": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"),
    "word": (".docx",),
    "sheet": (".xlsx", ".xlsm", ".xls", ".ods", ".csv"),
    "markdown": (".md", ".markdown"),
    "html": (".html", ".htm"),
    "text": (".txt", ".log", ".json", ".xml", ".py", ".r", ".sh", ".fasta", ".fa", ".vcf", ".tsv"),
    "office": (".pptx", ".ppt", ".pps", ".ppsx", ".odp", ".doc", ".odt", ".rtf"),
}
EXT_VIEWER = {ext: viewer for viewer, exts in VIEWERS.items() for ext in exts}
# type de support proposé d'après le fichier
VIEWER_KIND = {"video": "VIDEO", "audio": "AUDIO", "pdf": "PDF", "image": "IMAGE", "word": "DOC", "sheet": "SHEET",
               "markdown": "WEB", "html": "WEB", "text": "DOC"}
SLIDE_EXT = (".pptx", ".ppt", ".pps", ".ppsx", ".odp")
CONVERT_TIMEOUT = 180   # secondes
ACCEPT = ",".join(sorted(EXT_VIEWER))


class ConversionError(Exception):
    pass


def extension(name):
    return os.path.splitext(name or "")[1].lower()


def viewer_for(name):
    return EXT_VIEWER.get(extension(name), "file")


def kind_for(name):
    ext = extension(name)
    if ext in SLIDE_EXT:
        return "SLIDES"
    if ext in (".doc", ".odt", ".rtf"):
        return "DOC"
    return VIEWER_KIND.get(viewer_for(name))


def soffice():
    """Chemin de LibreOffice (variable LIBREOFFICE_PATH, PATH, emplacements Windows habituels) ou None."""
    candidates = [os.environ.get("LIBREOFFICE_PATH"), shutil.which("soffice"), shutil.which("libreoffice"),
                  r"C:\Program Files\LibreOffice\program\soffice.exe",
                  r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"]
    return next((c for c in candidates if c and Path(c).exists()), None)


def converted_pdf(resource):
    """PDF de prévisualisation d'un fichier bureautique (mis en cache dans media/mycolearn/apercus/)."""
    source = Path(resource.file.path)
    if not source.exists():
        raise ConversionError("Fichier introuvable sur le serveur.")
    stat = source.stat()
    key = hashlib.sha1(f"{source.name}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()[:12]
    out_dir = Path(settings.MEDIA_ROOT) / "mycolearn" / "apercus"
    target = out_dir / f"{resource.pk}-{key}.pdf"
    if target.exists():
        return target
    exe = soffice()
    if not exe:
        raise ConversionError("LibreOffice n'est pas installé sur le serveur : l'aperçu de ce format est "
                              "indisponible (voir le guide de mise en production).")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mycogen-lo-", ignore_cleanup_errors=True) as tmp:
        profile = Path(tmp, "profile").as_uri()          # profil isolé : conversions simultanées possibles
        cmd = [exe, f"-env:UserInstallation={profile}", "--headless", "--norestore", "--convert-to", "pdf",
               "--outdir", tmp, str(source)]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=CONVERT_TIMEOUT,
                           check=False)
        except subprocess.TimeoutExpired:
            raise ConversionError("La conversion a pris trop de temps.")
        produced = Path(tmp, source.with_suffix(".pdf").name)
        if not produced.exists():
            raise ConversionError("La conversion du fichier en PDF a échoué.")
        for old in out_dir.glob(f"{resource.pk}-*.pdf"):   # anciennes versions du même support
            old.unlink(missing_ok=True)
        shutil.move(str(produced), target)
    return target
