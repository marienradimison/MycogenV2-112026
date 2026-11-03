from pathlib import Path

from django.conf import settings


def asset_version():
    """Numéro de version des CSS/JS (date de dernière modification) : force le rechargement
    par les navigateurs après chaque mise à jour, au lieu d'utiliser une ancienne copie en cache."""
    newest = 0
    for d in getattr(settings, "STATICFILES_DIRS", []):
        for sub in ("css", "js"):
            for f in Path(d, sub).glob("*.*"):
                newest = max(newest, int(f.stat().st_mtime))
    return newest


def lab(request):
    from .menu import build_menu

    ctx = {
        "LAB_NAME": settings.LAB_NAME,
        "LAB_INSTITUTION": settings.LAB_INSTITUTION,
        "LAB_DEPARTMENT": settings.LAB_DEPARTMENT,
        "MENU": [],
        "SUBNAV": None,
        "THEME": "light",
        "PROFILE": None,
        "V": asset_version(),
    }
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        from .models import UserProfile

        profile = UserProfile.objects.filter(user=user).first()
        ctx.update({
            **dict(zip(("MENU", "SUBNAV"), build_menu(user, request))),
            "PROFILE": profile,
            "THEME": profile.theme if profile else "light",
            "OPEN_SUPPORT": _open_support() if user.is_staff else 0,
        })
    return ctx


def _open_support():
    from .models import BugReport, PasswordResetRequest

    return (BugReport.objects.filter(status="OPEN").count()
            + PasswordResetRequest.objects.filter(status="OPEN").count())
