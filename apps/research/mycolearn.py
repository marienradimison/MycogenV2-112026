"""MycoLearn — médiathèque de l'unité : vidéos, audio, présentations, PDF, infographies, liens, parcours.

    Accueil : à la une, « Continuer », « Ma liste », nouveautés, plus consultés, collections, rangées par domaine.
    Lecteur : vidéo / audio avec reprise de lecture, PDF, image, YouTube / Vimeo intégrés, liens.
    Suivi personnel (LearningActivity) : position de lecture, terminé, favoris.
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count, F, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.crud import Crud, safe_next

from .models import CollectionItem, LearningActivity, LearningCollection, LearningDomain, LearningResource
from .viewers import ConversionError, converted_pdf, soffice

ROW = 12          # supports par rangée
VIEWER_LABELS = {"video": "Lecteur vidéo", "audio": "Lecteur audio", "pdf": "Document PDF", "image": "Image",
                 "word": "Document Word", "sheet": "Classeur (Excel / CSV)", "markdown": "Document Markdown",
                 "text": "Fichier texte", "html": "Page HTML (isolée)", "office": "Présentation / document Office (aperçu PDF)",
                 "embed": "Vidéo en ligne", "web": "Page web", "file": "Fichier"}
VIEW_GAP = timedelta(minutes=30)   # une consultation comptée au plus toutes les 30 min par utilisateur
SORTS = {"recent": ("Plus récents", "-created_at"), "popular": ("Plus consultés", "-view_count"),
         "title": ("Titre A → Z", "title")}


def visible_resources(user):
    qs = LearningResource.objects.select_related("domain")
    return qs if user.has_perm("research.change_learningresource") else qs.filter(published=True)


def with_activity(resources, user):
    """Associe à chaque support l'activité de l'utilisateur (progression, favori) : r.act."""
    resources = list(resources)
    acts = {a.resource_id: a for a in LearningActivity.objects.filter(user=user, resource__in=resources)}
    for r in resources:
        r.act = acts.get(r.pk)
    return resources


def resource_context(obj, request):
    """Lecteur : activité de l'utilisateur, collection en cours (?collection=), supports liés ; compte la consultation."""
    user = request.user
    act, _ = LearningActivity.objects.get_or_create(user=user, resource=obj)
    now = timezone.now()
    if not act.last_viewed_at or now - act.last_viewed_at > VIEW_GAP:
        LearningResource.objects.filter(pk=obj.pk).update(view_count=F("view_count") + 1)
        obj.view_count += 1
    act.last_viewed_at = now
    viewable = obj.media not in ("file",) and not (obj.media == "office" and not soffice())
    if viewable and obj.media not in ("video", "audio", "embed") and not act.completed:   # document lu = terminé
        act.completed = True
    act.save()

    collection, playlist, prev_item, next_item = None, [], None, None
    cid = request.GET.get("collection") or ""
    if cid.isdigit():
        collection = LearningCollection.objects.filter(pk=cid, items__resource=obj).first()
    if collection is None:
        item = obj.collection_items.select_related("collection").filter(collection__published=True).first()
        collection = item.collection if item else None
    if collection:
        playlist = with_activity(collection.ordered_resources(), user)
        ids = [r.pk for r in playlist]
        if obj.pk in ids:
            i = ids.index(obj.pk)
            prev_item = playlist[i - 1] if i > 0 else None
            next_item = playlist[i + 1] if i + 1 < len(playlist) else None
    related = with_activity(visible_resources(user).filter(domain=obj.domain).exclude(pk=obj.pk)
                            .order_by("-view_count", "-created_at")[:6], user)
    return {"act": act, "collection": collection, "playlist": playlist, "prev_item": prev_item,
            "next_item": next_item, "related": related, "can_manage": user.has_perm("research.change_learningresource"),
            "can_convert": bool(soffice()) if obj.media == "office" else True,
            "viewer_label": VIEWER_LABELS.get(obj.media, "Fichier")}


def collection_context(obj, request):
    resources = with_activity(obj.ordered_resources(published_only=not request.user.has_perm(
        "research.change_learningresource")), request.user)
    done = sum(1 for r in resources if r.act and r.act.completed)
    resume = next((r for r in resources if not (r.act and r.act.completed)), resources[0] if resources else None)
    return {"resources": resources, "done": done, "percent": int(100 * done / len(resources)) if resources else 0,
            "resume": resume, "can_manage": request.user.has_perm("research.change_learningcollection")}


CRUDS = [
    Crud(
        LearningDomain, "domain",
        fields=["name", "icon", "description", "order"],
        list_display=["name", "description", "icon", "order"],
        search_fields=["name", "description"],
        icon="bi-collection",
        header_links=[("MycoLearn", "research:mycolearn", "bi-mortarboard")],
    ),
    Crud(
        LearningResource, "learning",
        fields=["title", "domain", "kind", "level", "language", "file", "url", "thumbnail", "description", "author",
                "duration_min", "tags", "featured", "published"],
        list_display=["title", "domain", "kind", "level", "language", "author", "view_count", "featured", "published"],
        search_fields=["title", "description", "author", "tags", "domain__name"],
        list_filter=["domain", "kind", "level", "language", "featured", "published"],
        icon="bi-mortarboard",
        detail_template="research/learning_detail.html",
        extra_context=resource_context,
        header_links=[("Médiathèque", "research:mycolearn", "bi-collection-play")],
    ),
    Crud(
        LearningCollection, "collection",
        fields=["title", "domain", "level", "description", "cover", "published"],
        list_display=["title", "domain", "level", "published"],
        search_fields=["title", "description"],
        list_filter=["domain", "level", "published"],
        icon="bi-collection-play",
        detail_template="research/collection_detail.html",
        extra_context=collection_context,
        header_links=[("Médiathèque", "research:mycolearn", "bi-collection-play")],
    ),
    Crud(
        CollectionItem, "collectionitem",
        fields=["collection", "resource", "order"],
        list_display=["collection", "order", "resource"],
        search_fields=["collection__title", "resource__title"],
        list_filter=["collection"],
        icon="bi-list-ol",
    ),
]


@login_required
@permission_required("research.view_learningresource", raise_exception=True)
def mycolearn(request):
    """Accueil de la médiathèque (rangées) ou résultats d'une recherche / d'un filtre (grille)."""
    user = request.user
    base = visible_resources(user)
    manage = user.has_perm("research.change_learningresource")
    visible = Q(resources__isnull=False) if manage else Q(resources__published=True)
    domains = LearningDomain.objects.annotate(n=Count("resources", filter=visible))

    f = {k: (request.GET.get(k) or "").strip() for k in ("q", "domaine", "type", "niveau", "langue", "tag", "liste", "tri")}
    domain = domains.filter(pk=f["domaine"]).first() if f["domaine"].isdigit() else None
    searching = any(f[k] for k in ("q", "domaine", "type", "niveau", "langue", "tag", "liste", "tri"))
    ctx = {"domains": domains, "domain": domain, "f": f, "kinds": LearningResource.KINDS,
           "levels": LearningResource.LEVELS, "languages": LearningResource.LANGUAGES, "sorts": SORTS,
           "manage": manage, "can_add": user.has_perm("research.add_learningresource"),
           "can_domains": user.has_perm("research.change_learningdomain"),
           "can_collections": user.has_perm("research.add_learningcollection"),
           "total": base.count(), "results": None}

    if searching:
        qs = base
        if domain:
            qs = qs.filter(domain=domain)
        if f["type"] in dict(LearningResource.KINDS):
            qs = qs.filter(kind=f["type"])
        if f["niveau"] in dict(LearningResource.LEVELS):
            qs = qs.filter(level=f["niveau"])
        if f["langue"] in dict(LearningResource.LANGUAGES):
            qs = qs.filter(language=f["langue"])
        if f["tag"]:
            qs = qs.filter(tags__icontains=f["tag"])
        if f["q"]:
            qs = qs.filter(Q(title__icontains=f["q"]) | Q(description__icontains=f["q"]) |
                           Q(author__icontains=f["q"]) | Q(tags__icontains=f["q"]))
        if f["liste"] == "favoris":
            qs = qs.filter(activity__user=user, activity__favorite=True)
        elif f["liste"] == "encours":
            qs = qs.filter(activity__user=user, activity__position__gt=0, activity__completed=False)
        qs = qs.order_by(SORTS.get(f["tri"], SORTS["recent"])[1], "title")
        ctx["results"] = with_activity(qs[:300], user)
        return render(request, "research/mycolearn.html", ctx)

    mine = LearningActivity.objects.filter(user=user).select_related("resource", "resource__domain")
    if not manage:
        mine = mine.filter(resource__published=True)
    rows = []

    def row(key, title, icon, resources, more=None):
        resources = with_activity(resources, user)
        if resources:
            rows.append({"key": key, "title": title, "icon": icon, "items": resources, "more": more})

    row("continue", "Continuer", "bi-play-btn",
        [a.resource for a in mine.filter(position__gt=0, completed=False).order_by("-last_viewed_at")[:ROW]],
        "?liste=encours")
    row("mylist", "Ma liste", "bi-bookmark-heart",
        [a.resource for a in mine.filter(favorite=True).order_by("-last_viewed_at")[:ROW]], "?liste=favoris")
    row("new", "Nouveautés", "bi-stars", base.order_by("-created_at")[:ROW], "?tri=recent")
    row("popular", "Les plus consultés", "bi-graph-up-arrow", base.filter(view_count__gt=0).order_by("-view_count")[:ROW])
    for d in domains:
        if d.n:
            row(f"domain-{d.pk}", d.name, d.icon, base.filter(domain=d).order_by("-featured", "-created_at")[:ROW],
                f"?domaine={d.pk}")
    collections = LearningCollection.objects.annotate(n=Count("items"))
    if not user.has_perm("research.change_learningcollection"):
        collections = collections.filter(published=True)
    ctx.update({
        "rows": rows, "collections": [c for c in collections if c.n],
        "featured": with_activity(base.filter(featured=True).order_by("-created_at")[:5], user),
    })
    return render(request, "research/mycolearn.html", ctx)


@login_required
@permission_required("research.view_learningresource", raise_exception=True)
@require_POST
def progress(request, pk):
    """Position de lecture envoyée par le lecteur (vidéo / audio) : reprise et « terminé » (≥ 90 %)."""
    resource = get_object_or_404(visible_resources(request.user), pk=pk)
    act, _ = LearningActivity.objects.get_or_create(user=request.user, resource=resource)
    try:
        position = max(float(request.POST.get("position", 0)), 0)
        duration = max(float(request.POST.get("duration", 0)), 0)
    except ValueError:
        return JsonResponse({"ok": False}, status=400)
    act.position, act.duration = position, duration or act.duration
    if request.POST.get("ended") == "1" or (act.duration and position >= 0.9 * act.duration):
        act.completed, act.position = True, 0
    act.last_viewed_at = timezone.now()
    act.save()
    if act.duration and not resource.duration_min:     # durée déduite du fichier
        LearningResource.objects.filter(pk=pk).update(duration_min=max(1, round(act.duration / 60)))
    return JsonResponse({"ok": True, "completed": act.completed, "percent": act.percent})


@login_required
@permission_required("research.view_learningresource", raise_exception=True)
@require_POST
def favorite(request, pk):
    """Ajoute / retire un support de « Ma liste »."""
    resource = get_object_or_404(visible_resources(request.user), pk=pk)
    act, _ = LearningActivity.objects.get_or_create(user=request.user, resource=resource)
    act.favorite = not act.favorite
    act.save(update_fields=["favorite"])
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"ok": True, "favorite": act.favorite})
    return redirect(safe_next(request, request.POST.get("next"), resource.get_absolute_url()))


@login_required
@permission_required("research.view_learningresource", raise_exception=True)
@require_POST
def mark_done(request, pk):
    """Marque un support comme terminé (ou le remet à « non terminé »)."""
    resource = get_object_or_404(visible_resources(request.user), pk=pk)
    act, _ = LearningActivity.objects.get_or_create(user=request.user, resource=resource)
    act.completed = not act.completed
    act.position = 0
    act.save(update_fields=["completed", "position"])
    return redirect(safe_next(request, request.POST.get("next"), resource.get_absolute_url()))


@login_required
@permission_required("research.view_learningresource", raise_exception=True)
@xframe_options_sameorigin
def preview_pdf(request, pk):
    """Aperçu PDF d'un fichier bureautique (PowerPoint, .doc, .odt…) converti par LibreOffice, affiché dans le lecteur."""
    resource = get_object_or_404(visible_resources(request.user), pk=pk)
    if not resource.file or resource.media != "office":
        raise Http404
    try:
        path = converted_pdf(resource)
    except ConversionError as exc:
        return HttpResponse(f"<p style='font-family:sans-serif;padding:2rem'>{exc}</p>", status=503)
    resp = FileResponse(open(path, "rb"), content_type="application/pdf")
    resp["Content-Disposition"] = "inline"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


@login_required
@permission_required("research.view_learningresource", raise_exception=True)
@xframe_options_sameorigin
def html_frame(request, pk):
    """Page HTML d'un support, servie dans un bac à sable (CSP sandbox, origine opaque) : ses scripts éventuels
    s'exécutent sans accès aux cookies, à la session ni aux pages de MYCOGEN."""
    resource = get_object_or_404(visible_resources(request.user), pk=pk)
    if not resource.file or resource.media not in ("html", "markdown", "text"):
        raise Http404
    with resource.file.open("rb") as f:
        data = f.read()
    resp = HttpResponse(data, content_type="text/html; charset=utf-8" if resource.media == "html"
                        else "text/plain; charset=utf-8")
    resp["Content-Security-Policy"] = "sandbox allow-scripts allow-popups allow-forms allow-modals"
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Referrer-Policy"] = "no-referrer"
    return resp
