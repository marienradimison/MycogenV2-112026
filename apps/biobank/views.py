from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.core.crud import Crud, log
from apps.core.forms import LimsModelForm, lims_formfield
from apps.core.models import ActivityLog, Sample

from .models import (PRESERVATIONS, BiobankItem, BoxMovement, InventoryLine, InventorySession, Movement,
                     StorageBox, StorageUnit, level_code)

# ---------------------------------------------------------------------------
# Formulaires
# ---------------------------------------------------------------------------


class ItemForm(LimsModelForm):
    preservations = PRESERVATIONS  # suggestions du champ « solution de conservation »

    class Meta:
        model = BiobankItem
        fields = ["item_type", "sample", "parent", "project", "label", "preservation", "quantity", "unit",
                  "concentration", "purity_260_280", "box", "position", "stored_on", "status", "freeze_thaw", "notes"]
        formfield_callback = lims_formfield
        help_texts = {"sample": "Le code de l'aliquot sera le n° de l'échantillon (26-4244, puis 26-4244-2…)",
                      "project": "Repris de l'échantillon source", "label": "Identifiant externe saisi à l'enregistrement de "
                                                                             "l'échantillon source"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["preservation"].widget.attrs["list"] = "preservations"
        self.fields["box"].queryset = StorageBox.objects.select_related("unit")
        self.fields["box"].label_from_instance = lambda b: b.path


class BoxForm(LimsModelForm):
    class Meta:
        model = StorageBox
        fields = ["item_type", "unit", "shelf", "rack", "number", "name", "rows", "cols", "content"]
        formfield_callback = lims_formfield


class MovementForm(LimsModelForm):
    class Meta:
        model = Movement
        fields = ["item", "type", "date", "quantity", "to_box", "to_position", "destination", "reason", "operator"]
        formfield_callback = lims_formfield

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["type"].choices = [c for c in Movement.TYPES if c[0] != "IN"]  # entrée : tracée à l'enregistrement
        self.fields["to_box"].queryset = StorageBox.objects.select_related("unit")
        self.fields["to_box"].label_from_instance = lambda b: b.path
        self.fields["item"].label_from_instance = lambda i: f"{i.code} — {i.get_item_type_display()}" + (
            f" ({i.path})" if i.box_id else "")


class InventoryForm(LimsModelForm):
    class Meta:
        model = InventorySession
        fields = ["unit", "shelf", "rack", "box", "performed_by", "notes"]
        formfield_callback = lims_formfield

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["box"].queryset = StorageBox.objects.select_related("unit")
        self.fields["box"].label_from_instance = lambda b: b.path

    def save(self, commit=True):
        creating = self.instance._state.adding
        obj = super().save(commit)
        if creating and commit:
            obj.populate()
        return obj


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def box_context(box, request):
    return {"units": StorageUnit.objects.filter(active=True),
            "moves": box.moves.select_related("operator")[:10],
            "trace_url": f"{reverse('biobank:trace')}?q={box.name}"}


def item_context(item, request):
    from django.utils.html import format_html
    return {"extra_details": [
        ("Localisation", format_html("<code>{}</code>", item.path) if item.path else "—"),
        ("Traçabilité", format_html('<a href="{}?q={}"><i class="bi bi-clock-history"></i> Historique complet</a>',
                                    reverse("biobank:trace"), item.code)),
    ]}


def inventory_context(session, request):
    lines = list(session.lines.select_related("box__unit", "expected_item", "checked_by"))
    groups = {}
    for line in lines:
        key = line.box_id or 0
        g = groups.setdefault(key, {"box": line.box, "box_line": None, "lines": []})
        if line.kind == "BOX":
            g["box_line"] = line
        else:
            g["lines"].append(line)
    editable = session.status == "OPEN" and request.user.has_perm("biobank.change_inventorysession")
    return {
        "groups": list(groups.values()), "counts": session.counts(), "editable": editable,
        "item_status": [c for c in InventoryLine.STATUS if c[0] != "UNREGISTERED"],
        "box_status": [c for c in InventoryLine.STATUS if c[0] in ("PENDING", "OK", "MISSING", "LABEL")],
        "can_validate": session.status == "SUBMITTED" and request.user.has_perm("biobank.validate_inventorysession"),
        "anomaly_labels": dict(InventoryLine.STATUS),
    }


CRUDS = [
    Crud(
        BiobankItem, "item",
        fields=ItemForm.Meta.fields,
        form_class=ItemForm,
        title="Aliquots & Souches",
        list_display=["code", "item_type", "sample", "label", "project", "preservation", "quantity", "unit",
                      ("path", "Localisation"), "status"],
        search_fields=["code", "label", "sample__code", "sample__patient__code", "parent__code", "box__name"],
        list_filter=["item_type", "status", "project", "box"],
        icon="bi-box-seam",
        form_template="biobank/item_form.html",
        extra_context=item_context,
    ),
    Crud(
        StorageBox, "box",
        fields=BoxForm.Meta.fields,
        form_class=BoxForm,
        list_display=["name", "item_type", "unit", "shelf", "rack", ("format_display", "Format"), "occupied",
                      "capacity"],
        search_fields=["name", "content", "unit__name"],
        list_filter=["item_type", "unit"],
        icon="bi-grid-3x3",
        detail_template="biobank/box_detail.html",
        extra_context=box_context,
    ),
    Crud(
        StorageUnit, "unit",
        fields=["name", "type", "room", "location", "serial_number", "active", "notes"],
        list_display=["name", "type", "room", "location", "serial_number", "active"],
        search_fields=["name", "location", "serial_number"],
        list_filter=["type", "active"],
        icon="bi-snow",
    ),
    Crud(
        Movement, "movement",
        fields=MovementForm.Meta.fields,
        form_class=MovementForm,
        list_display=["date", "item", "type", "from_location", "to_location", "quantity", "destination", "reason",
                      "operator"],
        search_fields=["item__code", "destination", "reason", "from_location", "to_location"],
        list_filter=["type", "operator"],
        icon="bi-arrow-left-right",
        exclude_urls=("update",),
    ),
    Crud(
        BoxMovement, "boxmove",
        fields=["box", "date", "from_location", "to_location", "reason", "operator"],
        list_display=["date", "box", "from_location", "to_location", "reason", "operator"],
        search_fields=["box__name", "from_location", "to_location", "reason"],
        icon="bi-arrows-move",
        exclude_urls=("create", "update", "delete"),
    ),
    Crud(
        InventorySession, "inventory",
        fields=InventoryForm.Meta.fields,
        form_class=InventoryForm,
        title="Inventaires",
        list_display=["code", ("level", "Niveau"), ("scope", "Périmètre"), "started_at", "performed_by", "status",
                      "validated_by", "validated_at"],
        search_fields=["code", "unit__name", "box__name", "notes"],
        list_filter=["status", "unit"],
        icon="bi-clipboard-check",
        detail_template="biobank/inventory_detail.html",
        extra_context=inventory_context,
        exclude_urls=("update",),
        header_links=[("Anomalies constatées", "biobank:anomaly_list", "bi-exclamation-triangle")],
    ),
    Crud(
        InventoryLine, "anomaly",
        fields=["session", "kind", "box", "position", "expected_item", "found_code", "found_position", "status",
                "comment", "checked_by", "checked_at", "corrected"],
        title="Anomalies d'inventaire",
        list_display=["session", "kind", "box", "position", "expected_item", "found_code", "found_position",
                      "status", "comment", "checked_by", "corrected"],
        search_fields=["session__code", "box__name", "expected_item__code", "found_code", "comment"],
        list_filter=["status", "session"],
        icon="bi-exclamation-triangle",
        exclude_urls=("create", "update", "delete"),
        queryset=lambda: InventoryLine.objects.filter(status__in=InventoryLine.ANOMALIES),
        header_links=[("Inventaires", "biobank:inventory_list", "bi-clipboard-check")],
    ),
]

# ---------------------------------------------------------------------------
# Aliquots : informations de l'échantillon source (remplissage du formulaire)
# ---------------------------------------------------------------------------

@login_required
@permission_required("biobank.add_biobankitem", raise_exception=True)
def source_info(request):
    """Projet et étiquette repris de l'échantillon source (ou de l'aliquot parent)."""
    sample, parent = None, None
    if (request.GET.get("parent") or "").isdigit():
        parent = BiobankItem.objects.filter(pk=request.GET["parent"]).select_related("sample").first()
    if (request.GET.get("sample") or "").isdigit():
        sample = Sample.objects.filter(pk=request.GET["sample"]).first()
    sample = sample or (parent.sample if parent else None)
    project_id = sample.project_id if sample and sample.project_id else (parent.project_id if parent else None)
    return JsonResponse({
        "sample": sample.pk if sample else None,
        "project": project_id,
        "label": sample.patient.code if sample and sample.patient_id else "",
        "code": sample.code if sample else "",
    })


# ---------------------------------------------------------------------------
# Boîtes : étiquette QR et déplacement
# ---------------------------------------------------------------------------

@login_required
@permission_required("biobank.view_storagebox", raise_exception=True)
def box_labels(request, pk=None):
    """Étiquette(s) des boîtes avec QR code : une boîte, ou plusieurs avec ?ids=1,2,3."""
    if pk:
        boxes = [get_object_or_404(StorageBox.objects.select_related("unit"), pk=pk)]
    else:
        ids = [int(x) for x in request.GET.get("ids", "").split(",") if x.strip().isdigit()]
        boxes = list(StorageBox.objects.filter(pk__in=ids).select_related("unit").order_by("name"))
    if not boxes:
        raise Http404("Aucune boîte")
    return render(request, "biobank/box_label.html", {"boxes": boxes})


@login_required
@permission_required("biobank.change_storagebox", raise_exception=True)
@require_POST
def box_move(request, pk):
    box = get_object_or_404(StorageBox.objects.select_related("unit"), pk=pk)
    unit = StorageUnit.objects.filter(pk=request.POST.get("unit") or 0).first()
    if not unit:
        messages.error(request, "Choisissez le congélateur de destination.")
        return redirect(box.get_absolute_url())
    before = box.path
    box.unit, box.shelf, box.rack = unit, level_code("E", request.POST.get("shelf")), level_code("R", request.POST.get("rack"))
    if box.path == before:
        messages.info(request, "La boîte est déjà à cet emplacement.")
        return redirect(box.get_absolute_url())
    if StorageBox.objects.filter(unit=unit, name=box.name).exclude(pk=box.pk).exists():
        messages.error(request, f"Une boîte « {box.name} » existe déjà dans {unit.name}.")
        return redirect(box.get_absolute_url())
    with transaction.atomic():
        box.updated_by = request.user
        box.save()
        BoxMovement.objects.create(box=box, from_location=before, to_location=box.path, operator=request.user,
                                   reason=request.POST.get("reason", "")[:255], created_by=request.user)
        log(request.user, "UPDATE", box, {"localisation": f"{before} → {box.path}"})
    messages.success(request, f"Boîte déplacée : {before} → {box.path}")
    return redirect(box.get_absolute_url())


# ---------------------------------------------------------------------------
# Inventaires
# ---------------------------------------------------------------------------

def _session_for_edit(request, pk):
    session = get_object_or_404(InventorySession, pk=pk)
    if session.status != "OPEN":
        messages.warning(request, "Cet inventaire n'est plus en cours : il ne peut plus être modifié.")
        return session, False
    return session, True


@login_required
@permission_required("biobank.change_inventorysession", raise_exception=True)
@require_POST
def inventory_save(request, pk):
    """Enregistre les constats saisis sur la fiche d'inventaire."""
    session, ok = _session_for_edit(request, pk)
    if not ok:
        return redirect(session.get_absolute_url())
    valid = dict(InventoryLine.STATUS)
    now, changed = timezone.now(), 0
    for line in session.lines.select_related("box"):
        status = request.POST.get(f"status_{line.pk}")
        if status is None:
            continue
        status = status if status in valid else line.status
        found = BiobankItem.normalize_position(request.POST.get(f"found_{line.pk}", ""))[:5]
        comment = request.POST.get(f"comment_{line.pk}", "")[:255]
        if (status, found, comment) != (line.status, line.found_position, line.comment):
            line.status, line.found_position, line.comment = status, found, comment
            line.checked_by, line.checked_at = request.user, now
            line.save()
            changed += 1
    messages.success(request, f"{changed} constat(s) enregistré(s).")
    return redirect(session.get_absolute_url())


@login_required
@permission_required("biobank.change_inventorysession", raise_exception=True)
@require_POST
def inventory_scan(request, pk):
    """Échantillon trouvé (code scanné ou saisi) : conforme, mal positionné ou non enregistré."""
    session, ok = _session_for_edit(request, pk)
    if not ok:
        return redirect(session.get_absolute_url())
    code = request.POST.get("code", "").strip()
    position = BiobankItem.normalize_position(request.POST.get("position", ""))[:5]
    box = session.boxes().filter(pk=request.POST.get("box") or 0).first()
    if not code:
        messages.error(request, "Indiquez le code lu.")
        return redirect(session.get_absolute_url())
    now = timezone.now()
    item = BiobankItem.objects.filter(code__iexact=code).first()
    line = session.lines.filter(expected_item=item).first() if item else None
    if line:
        line.found_code, line.checked_by, line.checked_at = code, request.user, now
        if (box and box.pk != line.box_id) or (position and position != line.position):
            line.status, line.found_position = "MISPLACED", position
            line.comment = line.comment or (f"Trouvé dans {box.name}" if box and box.pk != line.box_id else "")
        else:
            line.status = "OK"
        line.save()
        messages.success(request, f"{item.code} : {line.get_status_display().lower()}.")
    else:
        status = "MISPLACED" if item else "UNREGISTERED"
        comment = f"Enregistré ailleurs : {item.path or 'sans emplacement'}" if item else "Absent de Mycogen"
        InventoryLine.objects.create(session=session, kind="ITEM", box=box, expected_item=item, found_code=code,
                                     found_position=position, status=status, comment=comment[:255],
                                     checked_by=request.user, checked_at=now, created_by=request.user)
        messages.warning(request, f"{code} : {dict(InventoryLine.STATUS)[status].lower()} ({comment}).")
    return redirect(session.get_absolute_url())


@login_required
@permission_required("biobank.change_inventorysession", raise_exception=True)
@require_POST
def inventory_missing(request, pk):
    """Les aliquots et boîtes encore « à vérifier » sont déclarés manquants."""
    session, ok = _session_for_edit(request, pk)
    if ok:
        n = session.lines.filter(status="PENDING").update(status="MISSING", checked_by=request.user,
                                                          checked_at=timezone.now())
        messages.info(request, f"{n} élément(s) déclaré(s) manquant(s).")
    return redirect(session.get_absolute_url())


@login_required
@permission_required("biobank.change_inventorysession", raise_exception=True)
@require_POST
def inventory_submit(request, pk):
    session, ok = _session_for_edit(request, pk)
    if not ok:
        return redirect(session.get_absolute_url())
    pending = session.lines.filter(status="PENDING").count()
    if pending:
        messages.error(request, f"{pending} élément(s) restent à vérifier.")
        return redirect(session.get_absolute_url())
    session.status, session.submitted_at, session.updated_by = "SUBMITTED", timezone.now(), request.user
    session.save()
    log(request.user, "UPDATE", session, {"statut": "Soumis pour validation"})
    messages.success(request, "Inventaire soumis au responsable pour validation.")
    return redirect(session.get_absolute_url())


@login_required
@permission_required("biobank.validate_inventorysession", raise_exception=True)
@require_POST
def inventory_validate(request, pk):
    session = get_object_or_404(InventorySession, pk=pk)
    if session.status != "SUBMITTED":
        messages.warning(request, "Seul un inventaire soumis peut être validé ou renvoyé.")
        return redirect(session.get_absolute_url())
    comment = request.POST.get("comment", "")[:2000]
    if request.POST.get("decision") == "reopen":
        session.status, session.updated_by = "OPEN", request.user
        session.save()
        log(request.user, "UPDATE", session, {"statut": "Renvoyé pour reprise", "commentaire": comment})
        messages.info(request, "Inventaire renvoyé pour reprise.")
        return redirect(session.get_absolute_url())
    fixed = []
    with transaction.atomic():
        if request.POST.get("apply") == "1":
            for line in session.lines.filter(status="MISPLACED", corrected=False, expected_item__isnull=False,
                                             box__isnull=False).exclude(found_position="").select_related("expected_item", "box"):
                item = line.expected_item
                if item.check_position(line.box, line.found_position, exclude_pk=item.pk):
                    continue
                Movement.objects.create(item=item, type="MOVE", to_box=line.box, to_position=line.found_position,
                                        operator=request.user, created_by=request.user,
                                        reason=f"Correction après inventaire {session.code}")
                line.corrected = True
                line.save(update_fields=["corrected"])
                fixed.append(item.code)
        session.status, session.validated_by, session.validated_at = "VALIDATED", request.user, timezone.now()
        session.validation_comment, session.updated_by = comment, request.user
        session.save()
        log(request.user, "VALIDATE", session, {"commentaire": comment, "positions corrigées": ", ".join(fixed)})
    messages.success(request, "Inventaire validé." + (f" Positions corrigées : {', '.join(fixed)}." if fixed else ""))
    return redirect(session.get_absolute_url())


@login_required
@permission_required("biobank.change_inventorysession", raise_exception=True)
@require_POST
def inventory_cancel(request, pk):
    session = get_object_or_404(InventorySession, pk=pk)
    if session.status in ("OPEN", "SUBMITTED"):
        session.status, session.updated_by = "CANCELLED", request.user
        session.save()
        log(request.user, "UPDATE", session, {"statut": "Annulé"})
        messages.info(request, "Inventaire annulé.")
    return redirect(session.get_absolute_url())


# ---------------------------------------------------------------------------
# Traçabilité
# ---------------------------------------------------------------------------

ITEM_AUDIT_NAMES = ["élément de biobanque", BiobankItem._meta.verbose_name]  # ancien et nouveau nom du modèle
AUDIT_MODELS = ["élément de biobanque", BiobankItem._meta.verbose_name, StorageBox._meta.verbose_name,
                StorageUnit._meta.verbose_name, Movement._meta.verbose_name, InventorySession._meta.verbose_name]


def lineage(item):
    """Ascendance (de l'échantillon au parent direct) et descendance (arbre) d'un aliquot."""
    ancestors, p, seen = [], item.parent, {item.pk}
    while p and p.pk not in seen:
        ancestors.insert(0, p)
        seen.add(p.pk)
        p = p.parent

    def tree(node, depth=0):
        out = []
        for child in node.children.select_related("box__unit").order_by("created_at"):
            if child.pk in seen or depth > 10:
                continue
            seen.add(child.pk)
            out.append({"item": child, "depth": depth, "children": tree(child, depth + 1)})
        return out

    return ancestors, tree(item)


def flatten(nodes):
    for n in nodes:
        yield n
        yield from flatten(n["children"])


def item_dossier(item):
    ancestors, children = lineage(item)
    audit = ActivityLog.objects.filter(model__in=ITEM_AUDIT_NAMES, object_id=str(item.pk)).select_related("user")
    libraries = item.libraries.select_related("run") if hasattr(item, "libraries") else []
    return {"item": item, "ancestors": ancestors, "children": list(flatten(children)),
            "movements": item.movements.select_related("operator", "to_box"),
            "audit": audit[:100],
            "inventories": item.inventory_lines.select_related("session").order_by("-session__started_at")[:20],
            "libraries": libraries}


@login_required
@permission_required("biobank.view_movement", raise_exception=True)
def trace(request):
    """Traçabilité : dossier d'un aliquot, d'un échantillon ou d'une boîte ; journal des opérations ; audit."""
    q = request.GET.get("q", "").strip()
    tab = request.GET.get("onglet") or ("dossier" if q else "journal")
    ctx = {"q": q, "tab": tab}
    params = request.GET.copy()
    params.pop("page", None)
    ctx["tabs"] = []
    for key, label, icon in [("dossier", "Dossier", "bi-search"), ("journal", "Entrées, sorties et déplacements", "bi-list-ul"),
                             ("audit", "Journal d'audit", "bi-shield-lock")]:
        params["onglet"] = key
        ctx["tabs"].append((key, label, icon, f"?{params.urlencode()}", key == tab))

    if tab == "dossier" and q:
        item = BiobankItem.objects.filter(code__iexact=q).select_related("box__unit", "sample", "parent", "project").first()
        box = None if item else StorageBox.objects.filter(name__iexact=q).select_related("unit").first()
        sample = None if (item or box) else Sample.objects.filter(code__iexact=q).first()
        if item:
            ctx.update(item_dossier(item))
        elif box:
            ctx["box"] = box
            ctx["box_moves"] = box.moves.select_related("operator")
            ctx["box_items"] = box.items.select_related("sample").order_by("position")
            ctx["box_movements"] = (Movement.objects.filter(Q(from_location__contains=f"/{box.name}/") |
                                                            Q(to_location__contains=f"/{box.name}/") | Q(to_box=box))
                                    .select_related("item", "operator")[:200])
            ctx["audit"] = ActivityLog.objects.filter(model=StorageBox._meta.verbose_name,
                                                      object_id=str(box.pk)).select_related("user")[:100]
        elif sample:
            ctx["sample"] = sample
            roots = sample.biobank_items.filter(Q(parent__isnull=True) | ~Q(parent__sample=sample)).select_related("box__unit")
            ctx["sample_tree"] = []
            for root in roots:
                ctx["sample_tree"].append({"item": root, "depth": 0})
                ctx["sample_tree"] += [{"item": n["item"], "depth": n["depth"] + 1} for n in flatten(lineage(root)[1])]
        else:
            matches = BiobankItem.objects.filter(Q(code__icontains=q) | Q(label__icontains=q)).select_related("box__unit")[:30]
            ctx["matches"] = matches
            ctx["box_matches"] = StorageBox.objects.filter(name__icontains=q)[:20]
    elif tab == "journal":
        events = journal_events(request)
        ctx["page"] = Paginator(events, 50).get_page(request.GET.get("page"))
        ctx["types"] = Movement.TYPES + [("BOX", "Déplacement de boîte")]
        ctx["filters"] = {k: request.GET.get(k, "") for k in ("du", "au", "type", "operateur")}
        from django.contrib.auth import get_user_model
        ctx["operators"] = get_user_model().objects.filter(is_active=True).order_by("username")
    elif tab == "audit":
        logs = ActivityLog.objects.filter(model__in=AUDIT_MODELS).select_related("user")
        if q:
            logs = logs.filter(object_repr__icontains=q)
        ctx["page"] = Paginator(logs, 50).get_page(request.GET.get("page"))
    params["onglet"] = tab
    ctx["querystring"] = params.urlencode()
    return render(request, "biobank/trace.html", ctx)


def journal_events(request):
    """Mouvements d'aliquots et déplacements de boîtes, filtrés et triés du plus récent au plus ancien."""
    du, au = parse_date(request.GET.get("du") or ""), parse_date(request.GET.get("au") or "")
    kind, operator = request.GET.get("type", ""), request.GET.get("operateur", "")
    q = request.GET.get("q", "").strip()
    mv = Movement.objects.select_related("item", "operator", "to_box")
    bm = BoxMovement.objects.select_related("box", "operator")
    if du:
        mv, bm = mv.filter(date__date__gte=du), bm.filter(date__date__gte=du)
    if au:
        mv, bm = mv.filter(date__date__lte=au), bm.filter(date__date__lte=au)
    if operator.isdigit():
        mv, bm = mv.filter(operator_id=operator), bm.filter(operator_id=operator)
    if q:
        mv = mv.filter(Q(item__code__icontains=q) | Q(from_location__icontains=q) | Q(to_location__icontains=q))
        bm = bm.filter(Q(box__name__icontains=q) | Q(from_location__icontains=q) | Q(to_location__icontains=q))
    if kind == "BOX":
        mv = mv.none()
    elif kind:
        mv, bm = mv.filter(type=kind), bm.none()
    events = [{"date": m.date, "kind": m.get_type_display(), "type": m.type, "object": m.item, "code": m.item.code,
               "from": m.from_location, "to": m.to_location, "quantity": m.quantity, "operator": m.operator,
               "reason": m.reason or m.destination, "url": m.get_absolute_url()} for m in mv[:2000]]
    events += [{"date": b.date, "kind": "Déplacement de boîte", "type": "BOX", "object": b.box, "code": b.box.name,
                "from": b.from_location, "to": b.to_location, "quantity": None, "operator": b.operator,
                "reason": b.reason, "url": b.get_absolute_url()} for b in bm[:2000]]
    events.sort(key=lambda e: e["date"], reverse=True)
    return events


# ---------------------------------------------------------------------------
# Rapports
# ---------------------------------------------------------------------------

@login_required
@permission_required("biobank.view_biobankitem", raise_exception=True)
def reports(request):
    from . import reports as engine

    filters = engine.Filters(request)
    tab = request.GET.get("onglet") if request.GET.get("onglet") in dict((k, 1) for k, *_ in engine.TABS) else "effectifs"
    tables = engine.TAB_TABLES[tab](filters)
    fmt = request.GET.get("export")
    if fmt in ("csv", "xlsx", "pdf"):
        return engine.export(request, fmt, tab, tables, filters)
    params = request.GET.copy()
    params.pop("export", None)
    tabs = []
    for key, label, icon in engine.TABS:
        params["onglet"] = key
        tabs.append((key, label, icon, f"?{params.urlencode()}", key == tab))
    params["onglet"] = tab
    return render(request, "biobank/reports.html", {
        "tabs": tabs, "tab": tab, "tables": tables, "f": filters, "kpis": engine.kpis(filters),
        "export_query": params.urlencode(), "tab_label": dict((k, l) for k, l, _ in engine.TABS)[tab],
    })
