"""SGQ — Système de Gestion de la Qualité : statistiques d'activité et indicateurs de performance du laboratoire.

Modèle des tableaux : documents/Suivi_performance_labo_2025.xlsx
    - « Perfo par méthodes » : prélèvements, GNX-RIF, microscopie, cultures LJ / MGIT, DST, GNX-XDR, NPOC,
      concordances GNX / microscopie / cultures ;
    - « Performance globale » : indicateurs de détection DT-1 à DT-10 (onglet « Définitions des indicateurs ») ;
    - délais de rendu (réception → validation), d'après le guide « Navigation des indicateurs de tuberculose »
      (TB DIAH, 2021, indicateur DT-31).

Cohorte mensuelle : chaque résultat est compté dans le mois de RÉCEPTION de son échantillon
(les cultures « en cours » des derniers mois apparaissent ainsi comme dans le fichier modèle).
Les résultats annulés ne sont jamais comptés.
"""
import statistics
from collections import defaultdict
from datetime import datetime

from django.utils import timezone

MONTHS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre",
          "Novembre", "Décembre"]

GX_INVALID = {"INVALID", "ERROR", "NO_RESULT"}
GX_POSITIVE = {"TRACE", "VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH", "DETECTED"}
CMTB_POS = {"MTBC", "MIXED"}                      # CMTB + : identifiée comme CMTB
CMTB_NEG = {"NTM", "NON_MTBC", "NON_MYCO"}        # CMTB - : Non CMTB, MNT, Non mycobactérie
XDR_FIELDS = [("inh_result", "INH"), ("eto_result", "ETH"), ("fq_result", "FLQ"), ("amk_result", "AMK"),
              ("kan_result", "KAN"), ("cap_result", "CAP")]
XDR_INJECTABLES = {"AMK", "KAN", "CAP"}
KNOWN = {"R", "S"}
DETECTION = {"DETECTED", "NOT_DETECTED"}
DT_EXCLUDED_REASONS = {"FU", "EQA"}   # suivi de traitement, contrôle qualité : pas de nouveaux cas
# Codes de la bibliothèque affichés dans l'onglet « Définitions »
GLOSSARY = ["% MTB POSITIF", "% RIF-R", "% test invalid", "CMTB +", "CMTB -", "RTT", "TB-MR", "TB-XDR",
            "OFX", "LEV", "MOX", "AMK", "KAN", "CAP", "CFZ", "BDQ", "DLM", "LZD"]


class Tally:
    """Identifiants (résultats, échantillons ou patients) par clé et par mois : n = nombre d'identifiants distincts,
    le total annuel est l'union des mois (un patient vu deux mois différents compte une fois dans l'année)."""

    def __init__(self):
        self.data = defaultdict(lambda: [set() for _ in range(12)])

    def add(self, key, month, ident):
        self.data[key][month - 1].add(ident)

    def counts(self, key):
        months = self.data.get(key)
        return [len(s) for s in months] if months else [0] * 12

    def total(self, key):
        months = self.data.get(key)
        return len(set().union(*months)) if months else 0


# ---------------------------------------------------------------- mise en forme

def fmt_n(n):
    return f"{n:,}".replace(",", " ")


def fmt_pct(num, den):
    if not den:
        return None
    return round(100 * num / den, 1)


def pct_text(value):
    return "—" if value is None else f"{value:.1f}".replace(".", ",") + " %"


# ---------------------------------------------------------------- chargement des données

def year_bounds(year):
    tz = timezone.get_current_timezone()
    return datetime(year, 1, 1, tzinfo=tz), datetime(year + 1, 1, 1, tzinfo=tz)


def compute(year, project=None, validated_only=False):
    """Calcule toutes les tables de l'année ; renvoie {"tables": [...], "kpis": [...], "last_month": int}."""
    from apps.core.models import Sample
    from apps.diagnostic.models import DST, Culture, GeneXpertTest, Microscopy, NPOCTest

    start, end = year_bounds(year)
    scope = {"sample__received_at__gte": start, "sample__received_at__lt": end}
    samples = Sample.objects.filter(received_at__gte=start, received_at__lt=end)
    if project:
        scope["sample__project"] = project
        samples = samples.filter(project=project)

    def results(model, *fields):
        qs = model.objects.filter(**scope).exclude(result_status="CANCELLED")
        if validated_only:
            qs = qs.filter(result_status="VALIDATED")
        return qs.values("pk", "sample_id", *fields)

    t = Tally()
    month, patient, dt_ok, received = {}, {}, {}, {}
    for pk, rec, stype, conform, pid, reason in samples.values_list(
            "pk", "received_at", "sample_type", "conform", "patient_id", "reason"):
        local = timezone.localtime(rec)
        m = local.month
        month[pk], patient[pk], received[pk] = m, pid, local.date()
        dt_ok[pk] = reason not in DT_EXCLUDED_REASONS
        t.add("rec", m, pk)
        t.add("pulm" if stype in Sample.PULMONARY else "extra", m, pk)
        if not conform:
            t.add("rejected", m, pk)

    # agrégats par échantillon (concordances et indicateurs DT)
    ultra = defaultdict(lambda: {"done": False, "valid": False, "pos": False, "rif": set()})
    xdr = defaultdict(lambda: {"pos": False, "drugs": defaultdict(set)})
    smear, npoc, tested = defaultdict(set), defaultdict(set), set()
    culture = {"LJ": defaultdict(set), "MGIT": defaultdict(set)}
    cmtb = set()
    first_line, second_line = defaultdict(lambda: defaultdict(set)), defaultdict(lambda: defaultdict(set))
    tat = defaultdict(lambda: [[] for _ in range(12)])

    def delay(row, key, m):
        if row.get("validated_at"):
            days = (timezone.localtime(row["validated_at"]).date() - received[row["sample_id"]]).days
            tat[key][m - 1].append(max(days, 0))

    # GeneXpert MTB/RIF Ultra et MTB/XDR
    for r in results(GeneXpertTest, "assay", "mtb_result", "rif_result", "validated_at",
                     *[f for f, _ in XDR_FIELDS]):
        sid, m, pk = r["sample_id"], month[r["sample_id"]], r["pk"]
        tested.add(sid)
        invalid, pos = r["mtb_result"] in GX_INVALID, r["mtb_result"] in GX_POSITIVE
        if r["assay"] == "ULTRA":
            delay(r, "GNX-RIF", m)
            u = ultra[sid]
            u["done"] = True
            t.add("gx_done", m, pk)
            if invalid:
                t.add("gx_inv", m, pk)
                continue
            u["valid"] = True
            t.add("gx_valid", m, pk)
            if not pos:
                t.add("gx_neg", m, pk)
                continue
            u["pos"] = True
            t.add("gx_pos", m, pk)
            rif = {"NOT_DETECTED": "gx_rif_nd", "DETECTED": "gx_rif_r", "INDETERMINATE": "gx_rif_i"}.get(r["rif_result"])
            if rif:
                t.add(rif, m, pk)
            u["rif"].add(r["rif_result"])
        else:
            delay(r, "GNX-XDR", m)
            t.add("xdr_done", m, pk)
            if invalid:
                t.add("xdr_inv", m, pk)
                continue
            if not pos:
                t.add("xdr_neg", m, pk)
                continue
            t.add("xdr_pos", m, pk)
            x = xdr[sid]
            x["pos"] = True
            resistant = []
            for field, drug in XDR_FIELDS:
                x["drugs"][drug].add(r[field])
                if r[field] == "DETECTED":
                    resistant.append(drug)
            if len(resistant) == 1:
                t.add(f"xdr_mono_{resistant[0]}", m, pk)
            if "FLQ" in resistant and XDR_INJECTABLES.intersection(resistant):
                t.add("xdr_xdr", m, pk)

    # Microscopie
    for r in results(Microscopy, "grade", "validated_at"):
        sid, m, pk = r["sample_id"], month[r["sample_id"]], r["pk"]
        tested.add(sid)
        delay(r, "Microscopie", m)
        t.add("mi_done", m, pk)
        if r["grade"] == "NEG":
            t.add("mi_neg", m, pk)
            smear[sid].add("-")
        elif r["grade"] == "NA":
            t.add("mi_na", m, pk)
        else:
            t.add("mi_pos", m, pk)
            smear[sid].add("+")

    # Cultures LJ et MGIT
    for r in results(Culture, "medium", "result", "identification", "validated_at"):
        sid, m, pk, med = r["sample_id"], month[r["sample_id"]], r["pk"], r["medium"]
        tested.add(sid)
        delay(r, f"Cult-{med}", m)
        p = f"cu_{med}"
        t.add(f"{p}_done", m, pk)
        res = r["result"]
        if res == "NEGATIVE":
            t.add(f"{p}_neg", m, pk)
            culture[med][sid].add("-")
        elif res == "POSITIVE":
            t.add(f"{p}_pos", m, pk)
            culture[med][sid].add("+")
            if r["identification"] in CMTB_POS:
                t.add(f"{p}_cmtbp", m, pk)
                cmtb.add(sid)
            elif r["identification"] in CMTB_NEG:
                t.add(f"{p}_cmtbn", m, pk)
            else:
                t.add(f"{p}_idpend", m, pk)
        elif res == "CONTAMINATED":
            t.add(f"{p}_cont", m, pk)
        else:
            t.add(f"{p}_pend", m, pk)

    # Antibiogrammes phénotypiques
    dst_methods = set()
    for r in results(DST, "method", "panel", "results", "validated_at"):
        sid, m, pk, meth = r["sample_id"], month[r["sample_id"]], r["pk"], r["method"]
        dst_methods.add(meth)
        delay(r, "DST", m)
        line = "1" if r["panel"] == "FIRST" else "2"
        p = f"dst_{meth}_{line}"
        drugs = DST.PANEL_DRUGS["FIRST" if line == "1" else "SECOND"]
        values = {d: (r["results"] or {}).get(d, "") for d in drugs}
        agg = first_line if line == "1" else second_line
        for d, v in values.items():
            agg[sid][d].add(v)
        t.add(f"{p}_done", m, pk)
        resistant = [d for d, v in values.items() if v == "R"]
        if not any(v in ("R", "S", "I") for v in values.values()):
            t.add(f"{p}_pend", m, pk)
        if "I" in values.values():
            t.add(f"{p}_ind", m, pk)
        if len(resistant) == 1:
            t.add(f"{p}_mono", m, pk)
            t.add(f"{p}_mono_{resistant[0]}", m, pk)
        if line == "1" and {"RIF", "INH"} <= set(resistant):
            t.add(f"{p}_mr", m, pk)
        if line == "2" and set(DST.FLQ) & set(resistant) and set(DST.INJECTABLES) & set(resistant):
            t.add(f"{p}_xdr", m, pk)

    # NPOC (Pluslife)
    for r in results(NPOCTest, "mtb_result", "validated_at"):
        sid, m, pk = r["sample_id"], month[r["sample_id"]], r["pk"]
        tested.add(sid)
        delay(r, "NPOC", m)
        t.add("np_done", m, pk)
        if r["mtb_result"] in ("INVALID", "ERROR"):
            t.add("np_inv", m, pk)
            continue
        t.add("np_valid", m, pk)
        t.add("np_pos" if r["mtb_result"] == "DETECTED" else "np_neg", m, pk)
        if r["mtb_result"] == "DETECTED":
            npoc[sid].add("+")

    # Concordances (par échantillon) : GNX-RIF valide vs microscopie / cultures
    def status(values):
        return "+" if "+" in values else "-" if "-" in values else None

    pairs = [("smear", smear), ("lj", culture["LJ"]), ("mgit", culture["MGIT"])]
    for sid, u in ultra.items():
        if not u["valid"]:
            continue
        g = "+" if u["pos"] else "-"
        for key, data in pairs:
            other = status(data.get(sid, ()))
            if other:
                t.add(f"cc_{key}_{g}{other}", month[sid], sid)

    # Indicateurs DT (patients distincts, hors suivis de traitement et EEQ)
    def phen(agg, sid, drug):
        values = agg.get(sid, {}).get(drug, set())
        return "R" if "R" in values else "S" if "S" in values else None

    for sid in month:
        if not dt_ok[sid]:
            continue
        m, pid = month[sid], patient[sid]
        u, x = ultra.get(sid), xdr.get(sid)
        if sid in tested:
            t.add("dt_tested", m, pid)
        if u and u["done"]:
            t.add("dt1", m, pid)
        if u and u["pos"]:
            t.add("dt2", m, pid)
            if "DETECTED" in u["rif"]:
                t.add("dt3", m, pid)
        if (u and u["pos"]) or (x and x["pos"]) or "+" in smear.get(sid, ()) or sid in cmtb or npoc.get(sid):
            t.add("dt4", m, pid)
        # phénotypique (DST 1re / 2e ligne, toutes méthodes)
        rif, inh = phen(first_line, sid, "RIF"), phen(first_line, sid, "INH")
        if rif and inh:
            t.add("dt5_den", m, pid)
            others_r = any(phen(first_line, sid, d) == "R" for d in DST.PANEL_DRUGS["FIRST"] if d != "RIF")
            if rif == "R" and not others_r:
                t.add("dt5", m, pid)
            if rif == "R" and inh == "R":
                t.add("dt6", m, pid)
        flq = [phen(second_line, sid, d) for d in DST.FLQ]
        if any(flq):
            t.add("dt7_den", m, pid)
            if rif == "R" and inh == "R" and "R" in flq:
                t.add("dt7", m, pid)
        # génotypique : RIF (GNX-RIF), INH et FLQ (GNX-XDR)
        g_rif = "R" if u and "DETECTED" in u["rif"] else "S" if u and "NOT_DETECTED" in u["rif"] else None

        def geno(drug):
            values = x["drugs"].get(drug, set()) if x else set()
            return "R" if "DETECTED" in values else "S" if "NOT_DETECTED" in values else None

        g_inh, g_flq = geno("INH"), geno("FLQ")
        if g_rif and g_inh:
            t.add("dt8_den", m, pid)
            if g_rif == "R" and g_inh == "S":
                t.add("dt8", m, pid)
            if g_rif == "R" and g_inh == "R":
                t.add("dt9", m, pid)
        if g_flq:
            t.add("dt10_den", m, pid)
            if g_rif == "R" and g_inh == "R" and g_flq == "R":
                t.add("dt10", m, pid)

    return build(t, tat, year, sorted(dst_methods))


# ---------------------------------------------------------------- tables

def method_tables(dst_methods):
    """(clé, titre, code, lignes) ; ligne = ("n", libellé, clé, retrait) | ("pct", libellé, num, dén) | ("head", libellé)."""
    from apps.diagnostic.models import DST

    tables = [
        ("samples", "Type de prélèvements reçus", "", [
            ("n", "Total prélèvements reçus", "rec", 0),
            ("n", "Pulmonaire", "pulm", 1),
            ("n", "Extra-pulmonaire", "extra", 1),
            ("n", "Prélèvements rejetés", "rejected", 0),
            ("head", "Indicateurs de performance"),
            ("pct", "% prélèvements rejetés", "rejected", "rec"),
        ]),
        ("gnx", "GNX-RIF", "GNX-RIF", [
            ("n", "GNX-RIF réalisés", "gx_done", 0),
            ("n", "GNX-RIF valides", "gx_valid", 0),
            ("n", "MTB non détecté", "gx_neg", 0),
            ("n", "MTB détecté", "gx_pos", 0),
            ("n", "RIF non détectée", "gx_rif_nd", 1),
            ("n", "RIF détectée", "gx_rif_r", 1),
            ("n", "RIF indéterminée", "gx_rif_i", 1),
            ("n", "Invalid, error, no result", "gx_inv", 0),
            ("head", "Indicateurs de performance"),
            ("pct", "% MTB POSITIF", "gx_pos", "gx_valid"),
            ("pct", "% RIF-R", "gx_rif_r", "gx_pos"),
            ("pct", "% test invalid", "gx_inv", "gx_done"),
        ]),
        ("micro", "Microscopie (FLUO-AUR / ZN)", "FLUO-AUR", [
            ("n", "Microscopies réalisées", "mi_done", 0),
            ("n", "Frottis négatifs", "mi_neg", 0),
            ("n", "Frottis positifs", "mi_pos", 0),
            ("n", "Non interprétables", "mi_na", 0),
            ("head", "Indicateurs de performance"),
            ("pct", "% frottis POSITIF", "mi_pos", "mi_done"),
        ]),
    ]
    for med in ("LJ", "MGIT"):
        p = f"cu_{med}"
        tables.append((f"cult_{med.lower()}", f"Cult-{med}", f"Cult-{med}", [
            ("n", f"Cult-{med} réalisées", f"{p}_done", 0),
            ("n", f"Cult-{med} négatives", f"{p}_neg", 0),
            ("n", f"Cult-{med} positives", f"{p}_pos", 0),
            ("n", "CMTB +", f"{p}_cmtbp", 1),
            ("n", "CMTB -", f"{p}_cmtbn", 1),
            ("n", "Identification en attente", f"{p}_idpend", 1),
            ("n", "Contamination (RTT)", f"{p}_cont", 0),
            ("n", "En cours", f"{p}_pend", 0),
            ("head", "Indicateurs de performance"),
            ("pct", f"% Cult-{med} POSITIVES CMTB +", f"{p}_cmtbp", f"{p}_done"),
            ("pct", f"% Cult-{med} POSITIVES CMTB -", f"{p}_cmtbn", f"{p}_done"),
            ("pct", "% Contamination", f"{p}_cont", f"{p}_done"),
        ]))
    names = dict(DST.METHODS)
    for meth in ["MGIT"] + [m for m in dst_methods if m != "MGIT"]:
        p1, p2 = f"dst_{meth}_1", f"dst_{meth}_2"
        rows = [("n", "1ère ligne fait", f"{p1}_done", 0),
                ("n", "Mono-résistant", f"{p1}_mono", 0)]
        rows += [("n", f"Mono-{d}", f"{p1}_mono_{d}", 1) for d in DST.PANEL_DRUGS["FIRST"]]
        rows += [("n", "Multi-résistant (TB-MR)", f"{p1}_mr", 0),
                 ("n", "En cours", f"{p1}_pend", 0),
                 ("n", "Indéterminé (I)", f"{p1}_ind", 0),
                 ("n", "2ème ligne fait", f"{p2}_done", 0),
                 ("n", "Mono-résistant", f"{p2}_mono", 0)]
        rows += [("n", f"Mono-{d}", f"{p2}_mono_{d}", 1) for d in DST.PANEL_DRUGS["SECOND"]]
        rows += [("n", "TB-XDR", f"{p2}_xdr", 0),
                 ("n", "En cours", f"{p2}_pend", 0),
                 ("n", "Indéterminé (I)", f"{p2}_ind", 0),
                 ("head", "Indicateurs de performance"),
                 ("pct", "% TB-MR", f"{p1}_mr", f"{p1}_done"),
                 ("pct", "% TB-XDR", f"{p2}_xdr", f"{p2}_done"),
                 ("pct", "% indéterminé 1ère ligne", f"{p1}_ind", f"{p1}_done"),
                 ("pct", "% indéterminé 2ème ligne", f"{p2}_ind", f"{p2}_done")]
        label = "DST-MGIT" if meth == "MGIT" else "DST-LJ" if meth == "LJ" else f"DST ({names.get(meth, meth)})"
        tables.append((f"dst_{meth.lower()}", label, label, rows))
    tables += [
        ("xdr", "GNX-XDR", "GNX-XDR", [
            ("n", "GNX-XDR réalisés", "xdr_done", 0),
            ("n", "GNX-XDR non détecté", "xdr_neg", 0),
            ("n", "GNX-XDR détecté", "xdr_pos", 0),
            *[("n", f"Mono-{d}", f"xdr_mono_{d}", 1) for _, d in XDR_FIELDS],
            ("n", "TB-XDR", "xdr_xdr", 0),
            ("n", "Invalid, error, no result", "xdr_inv", 0),
            ("head", "Indicateurs de performance"),
            ("pct", "% TB-XDR", "xdr_xdr", "xdr_done"),
            ("pct", "% invalid", "xdr_inv", "xdr_done"),
        ]),
        ("npoc", "NPOC (Pluslife MTB)", "NPOC", [
            ("n", "NPOC réalisés", "np_done", 0),
            ("n", "NPOC valides", "np_valid", 0),
            ("n", "MTB non détecté", "np_neg", 0),
            ("n", "MTB détecté", "np_pos", 0),
            ("n", "Invalid, error", "np_inv", 0),
            ("head", "Indicateurs de performance"),
            ("pct", "% MTB POSITIF", "np_pos", "np_valid"),
            ("pct", "% test invalid", "np_inv", "np_done"),
        ]),
    ]
    return tables


CONCORDANCES = [
    ("cc_smear", "GNX / microscopie", "smear", "smear"),
    ("cc_mgit", "GNX / Cult-MGIT", "mgit", "Cult-MGIT"),
    ("cc_lj", "GNX / Cult-LJ", "lj", "Cult-LJ"),
]

# Indicateurs de détection (onglet « Définitions des indicateurs » du fichier modèle)
DT = [
    ("DT-1", "dt1", None,
     "Nombre de personnes ayant subi un dépistage de la TB active (GNX-RIF réalisé).", "—"),
    ("DT-2", "dt2", "dt1",
     "Personnes ayant reçu un résultat de dépistage positif pour la TB active (GNX+).",
     "GNX+ / personnes dépistées (DT-1) × 100"),
    ("DT-3", "dt3", "dt1",
     "Personnes ayant reçu un résultat de dépistage positif pour la TB-RR (GNX+ RIF-R).",
     "GNX+ RIF-R / personnes dépistées (DT-1) × 100"),
    ("DT-4", "dt4", "dt_tested",
     "Cas de TB bactériologiquement confirmés : GNX+, frottis +, culture (LJ/MGIT) + CMTB + ou NPOC +.",
     "Cas confirmés / patients présumés atteints de TB (au moins une analyse de diagnostic) × 100"),
    ("DT-5", "dt5", "dt5_den",
     "TB monorésistante à la rifampicine (RIF-R uniquement) par test de sensibilité phénotypique.",
     "RIF-R seule / patients ayant un DST 1ère ligne (RIF et INH rendus) × 100"),
    ("DT-6", "dt6", "dt5_den",
     "TB-MDR (RIF-R + INH-R) par test de sensibilité phénotypique.",
     "RIF-R + INH-R / patients ayant un DST 1ère ligne (RIF et INH rendus) × 100"),
    ("DT-7", "dt7", "dt7_den",
     "TB-XDR par test de sensibilité phénotypique : RIF-R + INH-R + FLQ-R (OFX, LEV ou MOX).",
     "RIF-R + INH-R + FLQ-R / patients ayant un DST 2ème ligne (FLQ rendue) × 100"),
    ("DT-8", "dt8", "dt8_den",
     "TB monorésistante à la rifampicine par test génotypique (RIF : GNX-RIF, INH : GNX-XDR).",
     "RIF-R et INH-S / patients ayant RIF et INH génotypiques rendus × 100"),
    ("DT-9", "dt9", "dt8_den",
     "TB-MDR (RIF-R + INH-R) par test génotypique.",
     "RIF-R + INH-R / patients ayant RIF et INH génotypiques rendus × 100"),
    ("DT-10", "dt10", "dt10_den",
     "TB-XDR par test génotypique : RIF-R + INH-R + FLQ-R.",
     "RIF-R + INH-R + FLQ-R / patients ayant FLQ génotypique rendue (GNX-XDR) × 100"),
]

TAT_FAMILIES = ["GNX-RIF", "GNX-XDR", "Microscopie", "NPOC", "Cult-LJ", "Cult-MGIT", "DST"]


def build(t, tat, year, dst_methods):
    from apps.core.models import AnalysisCode

    today = timezone.localdate()
    last = 12 if year < today.year else today.month if year == today.year else 0
    lib = {c.code: c.meaning for c in AnalysisCode.objects.filter(active=True)}

    def tip(label):
        for code in (label, label.replace("Mono-", ""), label.split(" (")[0]):
            if code in lib:
                return lib[code]
        return ""

    def cells(values):
        return [v if i < last else "" for i, v in enumerate(values)]   # mois à venir : cellule vide

    tables = []
    for key, title, code, spec in method_tables(dst_methods):
        rows = []
        for item in spec:
            if item[0] == "head":
                rows.append({"kind": "head", "label": item[1]})
            elif item[0] == "n":
                _, label, k, indent = item
                rows.append({"kind": "n", "label": label, "indent": indent, "title": tip(label),
                             "values": cells(t.counts(k)), "total": t.total(k)})
            else:
                _, label, num, den = item
                n, d = t.counts(num), t.counts(den)
                rows.append({"kind": "pct", "label": label, "title": tip(label),
                             "values": cells([fmt_pct(a, b) for a, b in zip(n, d)]),
                             "total": fmt_pct(t.total(num), t.total(den))})
        tables.append({"key": key, "title": title, "code": tip(code) and code, "rows": rows, "dual": False})

    # concordances : n et % (GNX+ : % des GNX+ comparables ; GNX- : % des GNX- comparables)
    for key, title, k, other in CONCORDANCES:
        rows = []
        combos = [("+", "+"), ("+", "-"), ("-", "+"), ("-", "-")]
        for g, o in combos:
            n = t.counts(f"cc_{k}_{g}{o}")
            den = [a + b for a, b in zip(t.counts(f"cc_{k}_{g}+"), t.counts(f"cc_{k}_{g}-"))]
            tn = t.total(f"cc_{k}_{g}{o}")
            tden = t.total(f"cc_{k}_{g}+") + t.total(f"cc_{k}_{g}-")
            rows.append({"kind": "dual", "label": f"GNX{g}/{other}{o}",
                         "values": cells(list(zip(n, [fmt_pct(a, b) for a, b in zip(n, den)]))),
                         "total": (tn, fmt_pct(tn, tden))})
        agree = [a + b for a, b in zip(t.counts(f"cc_{k}_++"), t.counts(f"cc_{k}_--"))]
        alls = [sum(t.counts(f"cc_{k}_{g}{o}")[i] for g, o in combos) for i in range(12)]
        tagree = t.total(f"cc_{k}_++") + t.total(f"cc_{k}_--")
        tall = sum(t.total(f"cc_{k}_{g}{o}") for g, o in combos)
        rows.append({"kind": "dual", "label": "Concordance globale", "strong": True,
                     "values": cells(list(zip(agree, [fmt_pct(a, b) for a, b in zip(agree, alls)]))),
                     "total": (tagree, fmt_pct(tagree, tall))})
        tables.append({"key": key, "title": title, "code": "", "rows": rows, "dual": True})

    # performance globale DT-1 à DT-10
    dt_rows = []
    for ref, num, den, definition, formula in DT:
        n = t.counts(num)
        pcts = [fmt_pct(a, b) for a, b in zip(n, t.counts(den))] if den else [None] * 12
        dt_rows.append({"kind": "dual", "label": ref, "title": lib.get(ref, definition),
                        "values": cells(list(zip(n, pcts))),
                        "total": (t.total(num), fmt_pct(t.total(num), t.total(den)) if den else None)})
    global_table = {"key": "global", "title": "Performance globale — indicateurs de détection de la TB (DT)",
                    "code": "", "rows": dt_rows, "dual": True}

    # délais de rendu : médiane (jours) réception → validation
    tat_rows = []
    for fam in TAT_FAMILIES:
        months = tat.get(fam)
        if not months or not any(months):
            continue
        every = [d for m in months for d in m]
        tat_rows.append({"kind": "dual", "label": fam,
                         "values": cells([(len(m), statistics.median(m) if m else None) for m in months]),
                         "total": (len(every), statistics.median(every))})
    tat_table = {"key": "tat", "title": "Délais de rendu — médiane en jours (réception → validation)",
                 "code": "", "rows": tat_rows, "dual": True, "tat": True}

    def total_of(table_key, label):
        for tb in tables:
            if tb["key"] == table_key:
                for r in tb["rows"]:
                    if r.get("label") == label:
                        return r["total"]
        return None

    kpis = [
        ("Prélèvements reçus", fmt_n(t.total("rec")), "bi-inbox", ""),
        ("% MTB POSITIF (GNX-RIF)", pct_text(total_of("gnx", "% MTB POSITIF")), "bi-virus", "accent"),
        ("% RIF-R", pct_text(total_of("gnx", "% RIF-R")), "bi-exclamation-triangle", ""),
        ("% contamination Cult-LJ", pct_text(total_of("cult_lj", "% Contamination")), "bi-droplet-half", ""),
    ]
    return {"tables": tables, "global": global_table, "tat": tat_table, "kpis": kpis, "last_month": last,
            "definitions": [(ref, lib.get(ref, ""), definition, formula) for ref, _, _, definition, formula in DT]}


def csv_rows(data, year):
    """Lignes de l'export CSV : toutes les tables, n et % séparés pour les tables doubles."""
    head = ["Tableau", "Ligne", *MONTHS, f"Total {year}"]
    yield head

    def num(v):
        return "" if v is None else str(v).replace(".", ",")

    for table in [*data["tables"], data["global"], data["tat"]]:
        yield [table["title"]]
        for r in table["rows"]:
            if r["kind"] == "head":
                yield ["", r["label"]]
            elif r["kind"] == "dual":
                first, second = ("n", "médiane (j)") if table.get("tat") else ("n", "%")
                yield ["", f"{r['label']} ({first})", *[num(v[0] if v else None) for v in r["values"]],
                       num(r["total"][0])]
                yield ["", f"{r['label']} ({second})", *[num(v[1] if v else None) for v in r["values"]],
                       num(r["total"][1])]
            else:
                yield ["", r["label"], *[num(v) for v in r["values"]], num(r["total"])]
        yield []
