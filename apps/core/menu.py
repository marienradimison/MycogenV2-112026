"""Navigation : modules de MYCOGEN.

La barre latérale affiche une entrée par module ; seul le module CNRM y déploie ses sous-modules.
Les autres modules ouvrent une page d'accueil (tuiles des sous-modules) et une barre de
sous-navigation s'affiche en haut de chacune de leurs pages.

Sous-module : (nom d'URL, icône, libellé, permission requise, description, préfixe d'URL couvert ou None)
"""
from django.urls import reverse

MODULES = [
    {"key": "dashboard", "label": "Tableau de bord", "icon": "bi-speedometer2", "url": "core:dashboard", "items": []},
    {"key": "cnrm", "label": "CNRM", "icon": "bi-hospital", "expanded": True, "items": [
        ("core:sample_list", "bi-droplet", "Échantillons", "core.view_sample", "Liste et fiches des échantillons", None),
        ("core:register", "bi-clipboard-plus", "Enregistrer", "core.add_sample", "Nouvel échantillon (patient + examens)", None),
        ("core:validation", "bi-patch-check", "Validation", "core.view_validation", "Résultats en attente de validation", None),
        ("core:facility_list", "bi-buildings", "Structures / CDT", "core.view_facility", "CDT et structures de provenance", None),
    ]},
    {"key": "analyses", "label": "Analyses TB", "icon": "bi-clipboard2-pulse", "items": [
        ("diagnostic:genexpert_live", "bi-cpu", "GeneXpert", "diagnostic.view_genexperttest",
         "Suivi en temps réel et tests RIF Ultra / XDR", "/diagnostic/genexpert/"),
        ("diagnostic:npoc_live", "bi-lightning-charge", "NPOC (Pluslife)", "diagnostic.view_npoctest",
         "Suivi en temps réel et tests NPOC", "/diagnostic/npoc/"),
        ("diagnostic:microscopy_list", "bi-eye", "Microscopie", "diagnostic.view_microscopy",
         "Ziehl-Neelsen et fluorescence", None),
        ("diagnostic:lj_home", "bi-thermometer-sun", "Culture LJ", "diagnostic.view_culture",
         "Étuve, ensemencement, lecture hebdomadaire, températures", lambda r: culture_page(r, "LJ")),
        ("diagnostic:lj_temperatures", "bi-thermometer-half", "Températures des étuves",
         lambda u: u.has_perm("diagnostic.add_temperaturelog") and not u.has_perm("diagnostic.view_culture"),
         "Relevés de température des étuves", "/diagnostic/lj/temperatures/"),
        ("diagnostic:culture_list?medium=MGIT", "bi-moisture", "Culture MGIT", "diagnostic.view_culture",
         "Suivi des cultures MGIT", lambda r: culture_page(r, "MGIT")),
        ("diagnostic:dst_list", "bi-capsule", "Antibiogramme (DST)", "diagnostic.view_dst",
         "Antibiogrammes phénotypiques", None),
        ("diagnostic:quantiferon_list", "bi-activity", "QuantiFERON-TB", "diagnostic.view_quantiferon",
         "QuantiFERON-TB Gold Plus", None),
    ]},
    {"key": "research", "label": "Recherche", "icon": "bi-journal-bookmark", "items": [
        ("research:project_list", "bi-journal-bookmark", "Projets", "research.view_project", "Projets de recherche", None),
        ("research:study_list", "bi-collection", "Études & cas", "research.view_study", "Études et cas par projet", None),
        ("research:run_list", "bi-diagram-3", "Runs de séquençage", "research.view_sequencingrun", "WGS, tNGS — ONT, Illumina",
         lambda r: r.path.startswith(("/recherche/run/", "/recherche/library/"))),
        ("research:pcrrun_list", "bi-thermometer-half", "Runs PCR (RISK6, Sweeney3)", "research.view_pcrrun", "Signatures transcriptionnelles",
         lambda r: r.path.startswith(("/recherche/pcrrun/", "/recherche/pcr/"))),
        ("research:lpa_list", "bi-bar-chart-steps", "LPA (Hain)", "research.view_lpatest", "MTBDRplus, MTBDRsl, CM/AS", None),
        ("research:notebook_list", "bi-journal-text", "Cahiers de laboratoire", "research.view_labnotebook",
         "Registre et contenu de tous les cahiers de labo", lambda r: r.path.startswith(("/recherche/notebook/", "/recherche/entry/"))),
        ("research:mycolearn", "bi-mortarboard", "MycoLearn", "research.view_learningresource",
         "Supports visuels pour apprendre, par domaine", lambda r: r.path.startswith(("/recherche/mycolearn/", "/recherche/learning/", "/recherche/domain/"))),
    ]},
    {"key": "biobank", "label": "Biobanque", "icon": "bi-box-seam", "items": [
        ("biobank:item_list", "bi-box-seam", "Aliquots & Souches", "biobank.view_biobankitem", "Prélèvements, souches, ADN, plasma, DBS…", None),
        ("biobank:box_list", "bi-grid-3x3", "Boîtes", "biobank.view_storagebox", "Plan des positions, étiquettes QR", None),
        ("biobank:unit_list", "bi-snow", "Congélateurs", "biobank.view_storageunit", "Unités de stockage", None),
        ("biobank:movement_list", "bi-arrow-left-right", "Mouvements", "biobank.view_movement",
         "Enregistrer les opérations : sorties, transferts, décongélations, déplacements", None),
        ("biobank:inventory_list", "bi-clipboard-check", "Inventaires", "biobank.view_inventorysession",
         "Vérifier la concordance entre la biobanque physique et Mycogen",
         lambda r: r.path.startswith(("/biobanque/inventory/", "/biobanque/anomaly/"))),
        ("biobank:trace", "bi-clock-history", "Traçabilité", "biobank.view_movement",
         "Historique complet d'un échantillon, d'un aliquot ou d'une boîte",
         lambda r: r.path.startswith(("/biobanque/tracabilite/", "/biobanque/boxmove/"))),
        ("biobank:reports", "bi-graph-up", "Rapports", "biobank.view_biobankitem",
         "Effectifs, occupation, capacités, entrées / sorties, inventaires", None),
    ]},
    {"key": "instruments", "label": "Automates", "icon": "bi-hdd-network", "items": [
        ("instruments:monitor", "bi-broadcast", "Suivi en temps réel", "instruments.view_instrumentmessage", "Tous les appareils", "/automates/$"),
        ("instruments:message_list", "bi-inbox", "Messages reçus", "instruments.view_instrumentmessage", "Messages et messages à traiter", None),
        ("instruments:instrument_list", "bi-hdd-network", "Configuration", "instruments.change_instrument", "Déclaration des appareils", None),
    ]},
    {"key": "stock", "label": "Stock", "icon": "bi-boxes", "url": "stock:home", "match": "/stock/", "perm": "stock.view_article",
     "items": []},
    {"key": "quality", "label": "SGQ", "icon": "bi-shield-check", "items": [
        ("quality:sgq", "bi-clipboard-data", "Suivi performance", "quality.view_sgq",
         "Statistiques d'activité et indicateurs de performance", None),
        ("quality:equipment_list", "bi-tools", "Matériels", "quality.view_equipment",
         "Gestion des matériels, maintenance, étalonnage et surveillance",
         lambda r: r.path == "/qualite/" or r.path.startswith("/qualite/equipment/")),
        ("quality:access_list", "bi-person-badge", "Accès aux salles", "quality.view_roomaccess",
         "Salles, personnes autorisées, plan de masse",
         lambda r: r.path.startswith(("/qualite/access/", "/room/", "/plan-de-masse/"))),
        ("quality:document_list", "bi-file-earmark-text", "DQ — Documents qualité", "quality.view_qualitydocument",
         "Manuels qualité, SOP, manuels clients, communiqués…", None),
    ]},
    {"key": "admin", "label": "Administration", "icon": "bi-gear", "items": [
        ("admin:index", "bi-people", "Utilisateurs & rôles", "is_staff", "Comptes, postes, rôles", "/admin/"),
        ("core:code_list", "bi-book", "Bibliothèque de codes", "core.view_analysiscode", "Codes d'analyses et de rôles", None),
        ("core:activity", "bi-clock-history", "Journal d'activité", "core.view_activitylog", "Audit : qui a fait quoi", None),
        ("core:support", "bi-life-preserver", "Support", "is_staff", "Bugs signalés, mots de passe", None),
    ]},
]


def culture_page(request, medium):
    """Culture LJ / MGIT : même liste et mêmes fiches ; le milieu décide du sous-module surligné."""
    path = request.path
    if medium == "LJ" and path.startswith("/diagnostic/lj/"):
        return True
    if not path.startswith("/diagnostic/culture/"):
        return False
    shown = request.GET.get("medium")
    match = getattr(request, "resolver_match", None)
    pk = match.kwargs.get("pk") if match else None
    if pk:
        from apps.diagnostic.models import Culture
        shown = Culture.objects.filter(pk=pk).values_list("medium", flat=True).first()
    elif match and match.url_name == "culture_create":
        shown = request.GET.get("medium") or "MGIT"
    return (shown or "MGIT") == medium


def allowed(user, perm):
    if callable(perm):
        return perm(user)
    if perm == "is_staff":
        return user.is_staff
    return perm is None or user.has_perm(perm)


def matches(prefix, path):
    if prefix.endswith("$"):          # correspondance exacte
        return path == prefix[:-1]
    return prefix != "/" and path.startswith(prefix)


def build_menu(user, request=None):
    """Retourne (entrées de la barre latérale, module courant avec ses sous-modules visibles)."""
    path = request.path if request is not None else "/"
    sidebar, current = [], None
    for m in MODULES:
        items = []
        for url, icon, label, perm, desc, match in m["items"]:
            if allowed(user, perm):
                name, _, query = url.partition("?")
                href = reverse(name) + (f"?{query}" if query else "")
                if callable(match):
                    active = request is not None and match(request)
                else:
                    active = path == href.split("?")[0] or matches(match or href.split("?")[0], path)
                items.append({"url": href, "icon": icon, "label": label, "desc": desc, "active": active})
        if m["items"] and not items:
            continue
        if not m["items"] and not allowed(user, m.get("perm")):
            continue
        hub = reverse(m["url"]) if m.get("url") else reverse("core:module", args=[m["key"]])
        active = any(i["active"] for i in items) or path == hub or (m.get("match") and matches(m["match"], path))
        entry = {"key": m["key"], "label": m["label"], "icon": m["icon"], "url": hub, "items": items,
                 "expanded": m.get("expanded", False), "active": bool(active)}
        sidebar.append(entry)
        if active and items and not entry["expanded"]:
            current = entry
    return sidebar, current


def module(user, key):
    for entry in build_menu(user)[0]:
        if entry["key"] == key:
            return entry
    return None
