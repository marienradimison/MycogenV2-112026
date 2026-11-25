"""Rapports de la biobanque : effectifs, occupation, capacités, entrées / sorties, inventaires.

Chaque onglet produit une liste de tableaux {title, headers, rows, foot, note}, réutilisée telle quelle
pour l'affichage, l'export CSV, Excel et PDF.
"""
import csv
import io
from collections import Counter, defaultdict

from django.db.models import Count
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.research.models import Project

from .models import TYPE_CHOICES, BiobankItem, BoxMovement, InventoryLine, InventorySession, Movement, StorageBox, StorageUnit

TABS = [
    ("effectifs", "Effectifs", "bi-bar-chart"),
    ("occupation", "Occupation", "bi-grid-3x3"),
    ("capacites", "Capacités disponibles", "bi-box"),
    ("flux", "Entrées et sorties", "bi-arrow-left-right"),
    ("inventaires", "Inventaires et non-conformités", "bi-clipboard-check"),
]
MONTHS = ["Janv.", "Févr.", "Mars", "Avr.", "Mai", "Juin", "Juil.", "Août", "Sept.", "Oct.", "Nov.", "Déc."]
TYPE_LABELS = dict(TYPE_CHOICES)


class Filters:
    def __init__(self, request):
        g = request.GET
        today = timezone.localdate()
        self.year = int(g["annee"]) if (g.get("annee") or "").isdigit() else None
        self.start, self.end = parse_date(g.get("du") or ""), parse_date(g.get("au") or "")
        self.project = Project.objects.filter(pk=g["projet"]).first() if (g.get("projet") or "").isdigit() else None
        self.item_type = g.get("type") if g.get("type") in TYPE_LABELS else ""
        self.host = (g.get("espece") or "").strip()
        self.unit = StorageUnit.objects.filter(pk=g["congelateur"]).first() if (g.get("congelateur") or "").isdigit() else None
        self.active_only = g.get("presents") == "1"
        first = BiobankItem.objects.order_by("stored_on").values_list("stored_on", flat=True).first()
        self.years = list(range(today.year, (first.year if first else today.year) - 1, -1))
        self.projects = Project.objects.order_by("code")
        self.units = StorageUnit.objects.order_by("name")
        self.types = TYPE_CHOICES
        self.hosts = sorted(set(BiobankItem.objects.exclude(sample__host="").exclude(sample__isnull=True)
                                .values_list("sample__host", flat=True)))
        # Période des entrées / sorties : dates saisies, sinon l'année choisie, sinon l'année en cours
        if not (self.start or self.end):
            y = self.year or today.year
            self.period = (today.replace(year=y, month=1, day=1), today.replace(year=y, month=12, day=31))
        else:
            self.period = (self.start or today.replace(year=2000, month=1, day=1), self.end or today)

    def items(self):
        qs = BiobankItem.objects.all()
        if self.year:
            qs = qs.filter(stored_on__year=self.year)
        if self.project:
            qs = qs.filter(project=self.project)
        if self.item_type:
            qs = qs.filter(item_type=self.item_type)
        if self.host:
            qs = qs.filter(sample__host=self.host)
        if self.unit:
            qs = qs.filter(box__unit=self.unit)
        if self.active_only:
            qs = qs.exclude(status__in=BiobankItem.GONE)
        return qs

    def boxes(self):
        qs = StorageBox.objects.select_related("unit")
        if self.unit:
            qs = qs.filter(unit=self.unit)
        if self.item_type:
            qs = qs.filter(item_type=self.item_type)
        return qs

    def describe(self):
        parts = [f"Année {self.year}" if self.year else "Toutes années"]
        if self.project:
            parts.append(f"projet {self.project.code}")
        if self.item_type:
            parts.append(TYPE_LABELS[self.item_type])
        if self.host:
            parts.append(f"espèce {self.host}")
        if self.unit:
            parts.append(f"congélateur {self.unit.name}")
        if self.active_only:
            parts.append("aliquots présents uniquement")
        return " · ".join(parts)


def pct(n, d):
    return f"{round(100 * n / d)} %" if d else "—"


def table(title, headers, rows, foot=None, note=""):
    return {"title": title, "headers": headers, "rows": rows, "foot": foot, "note": note}


# -- Effectifs ----------------------------------------------------------------

def effectifs(f):
    items = f.items()
    by_type_year = Counter(items.values_list("item_type", "stored_on__year"))
    years = sorted({y for _, y in by_type_year}, reverse=True)[:8]
    rows, col_tot = [], Counter()
    for code, label in TYPE_CHOICES:
        counts = [by_type_year.get((code, y), 0) for y in years]
        total = sum(n for (t, _), n in by_type_year.items() if t == code)
        if total:
            rows.append([label] + counts + [total])
            col_tot.update(dict(zip(years, counts)))
    tables = [table("Effectifs par type et par année de stockage", ["Type"] + [str(y) for y in years] + ["Total"], rows,
                    ["Total"] + [col_tot[y] for y in years] + [sum(r[-1] for r in rows)])]

    def grouped(title, field, empty):
        data = defaultdict(Counter)
        for key, t in items.values_list(field, "item_type"):
            data[key or empty][t] += 1
        types = [c for c, _ in TYPE_CHOICES if any(data[k][c] for k in data)]
        body = [[k] + [data[k][t] for t in types] + [sum(data[k].values())]
                for k in sorted(data, key=lambda k: -sum(data[k].values()))]
        return table(title, [title.split(" par ")[-1].capitalize()] + [TYPE_LABELS[t] for t in types] + ["Total"], body)

    tables.append(grouped("Effectifs par projet", "project__code", "Sans projet"))
    tables.append(grouped("Effectifs par espèce", "sample__host", "Non renseignée"))
    status = Counter(items.values_list("status", flat=True))
    tables.append(table("Effectifs par statut", ["Statut", "Nombre"],
                        [[label, status[code]] for code, label in BiobankItem.STATUS if status[code]]))
    return tables


# -- Occupation et capacités --------------------------------------------------

def _box_stats(f):
    occupied = dict(BiobankItem.objects.exclude(status__in=BiobankItem.GONE).values_list("box")
                    .annotate(n=Count("pk")).values_list("box", "n"))
    return [(b, occupied.get(b.pk, 0)) for b in f.boxes().order_by("unit__name", "shelf", "rack", "name")]


def occupation(f):
    stats = _box_stats(f)
    per_unit = defaultdict(lambda: [0, 0, 0])
    for b, n in stats:
        u = per_unit[b.unit]
        u[0] += 1
        u[1] += b.capacity
        u[2] += n
    units = [[u.name, u.get_type_display(), nb, cap, occ, cap - occ, pct(occ, cap)]
             for u, (nb, cap, occ) in sorted(per_unit.items(), key=lambda x: x[0].name)]
    tot = [sum(r[i] for r in units) for i in (2, 3, 4, 5)]
    return [
        table("Taux d'occupation des congélateurs", ["Congélateur", "Type", "Boîtes", "Capacité", "Occupées", "Libres",
                                                     "Occupation"], units,
              ["Total", "", *tot, pct(tot[2], tot[1])]),
        table("Taux d'occupation des boîtes", ["Boîte", "Localisation", "Type d'aliquot", "Format", "Occupées", "Libres",
                                               "Occupation"],
              [[b.name, b.path, b.get_item_type_display() or "—", f"{b.rows}x{b.cols}", n, b.capacity - n,
                pct(n, b.capacity)] for b, n in stats]),
    ]


def capacites(f):
    stats = _box_stats(f)
    by_type = defaultdict(lambda: [0, 0, 0])
    for b, n in stats:
        t = by_type[b.get_item_type_display() or "Non typée"]
        t[0] += 1
        t[1] += b.capacity - n
        t[2] += 1 if n >= b.capacity else 0
    full = [[b.name, b.path, n, b.capacity, pct(n, b.capacity)] for b, n in stats if b.capacity and n / b.capacity >= .9]
    empty_units = [[u.name, u.get_type_display(), u.room or "—"] for u in StorageUnit.objects.filter(active=True)
                   if not u.boxes.exists() and (not f.unit or u == f.unit)]
    return [
        table("Positions libres par type de boîte", ["Type de boîte", "Boîtes", "Positions libres", "Boîtes pleines"],
              [[k, *v] for k, v in sorted(by_type.items())],
              ["Total", sum(v[0] for v in by_type.values()), sum(v[1] for v in by_type.values()),
               sum(v[2] for v in by_type.values())]),
        table("Boîtes pleines ou presque (≥ 90 %)", ["Boîte", "Localisation", "Occupées", "Capacité", "Occupation"], full,
              note="Prévoir une nouvelle boîte du même type."),
        table("Congélateurs en service sans boîte", ["Congélateur", "Type", "Salle"], empty_units),
    ]


# -- Entrées et sorties -------------------------------------------------------

def flux(f):
    start, end = f.period
    mv = Movement.objects.filter(date__date__gte=start, date__date__lte=end)
    if f.project:
        mv = mv.filter(item__project=f.project)
    if f.item_type:
        mv = mv.filter(item__item_type=f.item_type)
    if f.host:
        mv = mv.filter(item__sample__host=f.host)
    if f.unit:
        mv = mv.filter(item__box__unit=f.unit)
    months = []
    d = start.replace(day=1)
    while d <= end and len(months) < 36:
        months.append((d.year, d.month))
        d = d.replace(year=d.year + (d.month == 12), month=d.month % 12 + 1)
    counts = Counter((m.type, m.date.year, m.date.month) for m in mv.only("type", "date"))
    labels = [f"{MONTHS[m - 1]} {y % 100:02d}" for y, m in months]
    rows = []
    for code, label in Movement.TYPES:
        values = [counts.get((code, y, m), 0) for y, m in months]
        if sum(values):
            rows.append([label] + values + [sum(values)])
    entries = sum(n for (t, *_), n in counts.items() if t in Movement.ENTRIES)
    exits = sum(n for (t, *_), n in counts.items() if t in Movement.EXITS)
    by_type = defaultdict(Counter)
    for t, item_type in mv.values_list("type", "item__item_type"):
        by_type[item_type][t] += 1
    moves = BoxMovement.objects.filter(date__date__gte=start, date__date__lte=end).count()
    period = f"du {start:%d/%m/%Y} au {end:%d/%m/%Y}"
    return [
        table(f"Bilan {period}", ["Indicateur", "Nombre"],
              [["Entrées (enregistrements et retours en stock)", entries], ["Sorties (sorties, transferts, épuisements, destructions)", exits],
               ["Décongélations", sum(n for (t, *_), n in counts.items() if t == "THAW")],
               ["Changements d'emplacement d'aliquots", sum(n for (t, *_), n in counts.items() if t == "MOVE")],
               ["Déplacements de boîtes", moves]]),
        table("Mouvements par mois", ["Mouvement"] + labels + ["Total"], rows),
        table("Mouvements par type d'aliquot", ["Type d'aliquot"] + [l for _, l in Movement.TYPES] + ["Total"],
              [[TYPE_LABELS.get(t, t)] + [c[k] for k, _ in Movement.TYPES] + [sum(c.values())]
               for t, c in sorted(by_type.items())]),
    ]


# -- Inventaires --------------------------------------------------------------

def inventaires(f):
    start, end = f.period
    sessions = InventorySession.objects.filter(started_at__date__gte=start, started_at__date__lte=end).select_related(
        "unit", "box", "performed_by", "validated_by")
    if f.unit:
        sessions = sessions.filter(unit=f.unit)
    rows = []
    for s in sessions:
        c = s.counts()
        rows.append([s.code, s.scope, f"{timezone.localtime(s.started_at):%d/%m/%Y}", s.get_status_display(),
                     str(s.performed_by or "—"), str(s.validated_by or "—"), sum(c.values()), c["OK"],
                     c["MISSING"], c["UNREGISTERED"], c["MISPLACED"], c["LABEL"]])
    lines = (InventoryLine.objects.filter(session__in=sessions, status__in=InventoryLine.ANOMALIES)
             .select_related("session", "box", "expected_item"))
    return [
        table(f"Inventaires du {start:%d/%m/%Y} au {end:%d/%m/%Y}",
              ["Inventaire", "Périmètre", "Date", "Statut", "Réalisé par", "Validé par", "Contrôles", "Conformes",
               "Manquants", "Non enregistrés", "Mal positionnés", "Étiquette / QR"], rows),
        table("Non-conformités constatées", ["Inventaire", "Boîte", "Position", "Aliquot", "Code lu", "Position constatée",
                                             "Constat", "Commentaire", "Corrigé"],
              [[l.session.code, l.box.name if l.box_id else "—", l.position or "—",
                l.expected_item.code if l.expected_item_id else "—", l.found_code or "—", l.found_position or "—",
                l.get_status_display(), l.comment, "Oui" if l.corrected else ""] for l in lines]),
    ]


TAB_TABLES = {"effectifs": effectifs, "occupation": occupation, "capacites": capacites, "flux": flux,
              "inventaires": inventaires}


def kpis(f):
    stats = _box_stats(f)
    cap, occ = sum(b.capacity for b, _ in stats), sum(n for _, n in stats)
    return [
        ("Aliquots présents", f.items().exclude(status__in=BiobankItem.GONE).count(), "bi-box-seam", ""),
        ("Boîtes", len(stats), "bi-grid-3x3", ""),
        ("Occupation", pct(occ, cap), "bi-pie-chart", ""),
        ("Positions libres", cap - occ, "bi-plus-square", ""),
    ]


# -- Exports ------------------------------------------------------------------

def export(request, fmt, tab, tables, f):
    stamp = f"{timezone.localdate():%Y%m%d}"
    name = f"biobanque_{tab}_{stamp}"
    if fmt == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{name}.csv"'
        resp.write("﻿")  # BOM UTF-8 : Excel affiche correctement les accents
        w = csv.writer(resp, delimiter=";", lineterminator="\r\n")
        w.writerow([f"Biobanque — {dict((k, l) for k, l, _ in TABS)[tab]}", f.describe()])
        for t in tables:
            w.writerow([])
            w.writerow([t["title"]])
            w.writerow(t["headers"])
            w.writerows(t["rows"])
            if t["foot"]:
                w.writerow(t["foot"])
        return resp
    if fmt == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb = Workbook()
        wb.remove(wb.active)
        used = set()
        for t in tables:
            title = "".join(c for c in t["title"] if c not in "[]:*?/\\")[:28] or "Tableau"
            while title in used:
                title = title[:26] + str(len(used))
            used.add(title)
            ws = wb.create_sheet(title)
            ws.append([t["title"]])
            ws["A1"].font = Font(bold=True, size=12)
            ws.append([f.describe()])
            ws.append([])
            ws.append(t["headers"])
            for cell in ws[4]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="3F8197")
            for r in t["rows"]:
                ws.append(r)
            if t["foot"]:
                ws.append(t["foot"])
                for cell in ws[ws.max_row]:
                    cell.font = Font(bold=True)
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in list(col)[3:]) if ws.max_row > 3 else 10
                ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 50)
        buf = io.BytesIO()
        wb.save(buf)
        resp = HttpResponse(buf.getvalue(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="{name}.xlsx"'
        return resp
    # PDF : rendu local par Edge/Chrome ; à défaut, page imprimable
    from apps.core.pdf import PdfError, html_to_pdf
    ctx = {"tables": tables, "tab_label": dict((k, l) for k, l, _ in TABS)[tab], "description": f.describe(),
           "now": timezone.localtime()}
    html = render_to_string("biobank/report_print.html", ctx, request)
    try:
        data = html_to_pdf(html)
    except PdfError as exc:
        return HttpResponse(render_to_string("biobank/report_print.html", {**ctx, "pdf_error": str(exc)}, request))
    resp = HttpResponse(data, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{name}.pdf"'
    return resp
