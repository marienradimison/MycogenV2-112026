"""Signatures des utilisateurs (paramétrées par l'administrateur dans la fiche utilisateur).

La signature est intégrée aux pages en « data URI » : elle s'affiche à l'écran comme dans les PDF
générés par le navigateur sans session, et le fichier n'est pas exposé par une URL publique.
"""
import base64
import mimetypes

from django.utils.html import format_html

MAX_BYTES = 2_000_000


def profile_of(user):
    if not user or not getattr(user, "pk", None):
        return None
    try:
        return user.profile
    except Exception:   # utilisateur sans profil
        return None


def signature_data_uri(user):
    """data:image/...;base64,… de la signature de l'utilisateur, ou "" s'il n'en a pas."""
    profile = profile_of(user)
    if not profile or not profile.signature:
        return ""
    try:
        f = profile.signature
        if f.size > MAX_BYTES:
            return ""
        f.open("rb")
        try:
            data = f.read()
        finally:
            f.close()
    except (OSError, ValueError):   # fichier absent du disque
        return ""
    mime = mimetypes.guess_type(f.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def signature_html(user, css_class="signature-img"):
    uri = signature_data_uri(user)
    if not uri:
        return ""
    profile = profile_of(user)
    return format_html('<img class="{}" src="{}" alt="Signature de {}">', css_class, uri, profile.signature_caption)


def caption(user):
    profile = profile_of(user)
    if profile:
        return profile.signature_caption
    return (user.get_full_name() or user.username) if user else ""
