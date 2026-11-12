"""Export CSV de la table des échantillons : une ligne par échantillon, patient + résultats de toutes les analyses.

Format défini par l'unité (fichier modèle « sample.csv ») : UTF-8 avec BOM, séparateur « ; », dates jj/mm/aaaa,
« NA » pour toute information non renseignée ou non applicable. La région est celle de la provenance / CDT. Les résultats sont écrits en majuscules sans
accents (NON DETECTE, POSITIF…), comme dans le modèle. Pour chaque analyse, le résultat le plus récent est exporté.
"""
import csv
import unicodedata

from django.http import HttpResponse
from django.utils import timezone

NA = "NA"

GX_MTB = {"NOT_DETECTED": "NON DETECTE", "TRACE": "TRACE", "VERY_LOW": "TRES FAIBLE", "LOW": "FAIBLE",
          "MEDIUM": "MOYEN", "HIGH": "ELEVE", "VERY_HIGH": "TRES ELEVE", "DETECTED": "DETECTE",
          "INVALID": "INVALIDE", "ERROR": "ERREUR", "NO_RESULT": "PAS DE RESULTAT"}
GX_RIF = {"DETECTED": "DETECTEE", "NOT_DETECTED": "NON DETECTEE", "INDETERMINATE": "INDETERMINEE"}
XDR_RS = {"DETECTED": "RESISTANT", "NOT_DETECTED": "SENSIBLE", "INDETERMINATE": "INDETERMINE"}
XDR_FIELDS = [("INH", "inh_result"), ("FLQ", "fq_result"), ("KAN", "kan_result"), ("CAP", "cap_result"),
              ("AMK", "amk_result"), ("ETH", "eto_result")]
GRADE_QUANT = {"NEG": "0", "SCANTY": "RARE", "1-19": "RARE", "1+": "100", "2+": "200", "3+": "300"}
CULTURE = {"PENDING": "EN COURS", "POSITIVE": "POSITIF", "NEGATIVE": "NEGATIF", "CONTAMINATED": "CONTAMINE"}
IDENT = {"MTBC": "CMTB", "NTM": "MNT", "NON_MTBC": "NON CMTB", "MIXED": "MIXTE CMTB + MNT",
         "NON_MYCO": "NON MYCOBACTERIE"}
DST_RS = {"R": "RESISTANT", "S": "SENSIBLE", "I": "INDETERMINE", "NF": "NON FAIT", "NA": NA}
POS_NEG = {"POS": "POSITIF", "NEG": "NEGATIF", "IND": "INDETERMINE",
           "DETECTED": "POSITIF", "NOT_DETECTED": "NEGATIF", "INVALID": "INDETERMINE", "ERROR": "INDETERMINE"}


def upper(text):
    """« Détecté » → « DETECTE » (majuscules sans accents, comme le modèle)."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().upper()


def val(v):
    if v is None or v == "":
        return NA
    if isinstance(v, bool):
        return "Oui" if v else "Non"
    return str(v)


def day(d):
    if not d:
        return NA
    if hasattr(d, "hour"):
        d = timezone.localtime(d).date()
    return d.strftime("%d/%m/%Y")


def rendered(r):
    """Date de rendu = date de validation du résultat."""
    return day(getattr(r, "validated_at", None))


def num(v):
    if v is None:
        return NA
    s = format(v, "f").rstrip("0").rstrip(".") if hasattr(v, "as_tuple") else str(v)
    return s.replace(".", ",")


def latest(objs, **match):
    for o in objs:   # déjà triés du plus récent au plus ancien
        if all(getattr(o, k) == v for k, v in match.items()):
            return o
    return None


# --- Colonnes par analyse : (en-têtes, fonction(résultat) -> valeurs) -----------------------------------

def gx_ultra(r):
    return [day(r.test_date), GX_MTB.get(r.mtb_result, upper(r.get_mtb_result_display())),
            GX_RIF.get(r.rif_result, NA), rendered(r)]


def gx_xdr(r):
    return ([day(r.test_date), GX_MTB.get(r.mtb_result, upper(r.get_mtb_result_display()))]
            + [XDR_RS.get(getattr(r, f), NA) for _, f in XDR_FIELDS] + [rendered(r)])


def microscopy(r):
    result = {"NEG": "NEGATIF", "NA": "NON INTERPRETABLE"}.get(r.grade, "POSITIF")
    quant = GRADE_QUANT.get(r.grade, NA)
    if r.grade == "SCANTY" and r.afb_count:
        quant = f"RARE ({r.afb_count})"
    return [day(r.test_date), result, quant, rendered(r)]


def culture(r):
    quant = NA
    if r.result == "NEGATIVE":
        quant = "0"
    elif r.result == "POSITIVE":
        quant = GRADE_QUANT.get(r.lj_grade, NA) if r.medium == "LJ" else NA
        if r.medium == "LJ" and r.colony_count:
            quant = str(r.colony_count)   # nombre exact de colonies
    cols = [day(r.inoculated_on), CULTURE.get(r.result, NA)]
    if r.medium == "LJ":
        cols.append(quant)
    return cols + [day(r.result_date), num(r.ttp_days), rendered(r), IDENT.get(r.identification, NA)]


def dst(drugs):
    def row(r):
        return [day(r.test_date), upper(r.get_panel_display())] + \
               [DST_RS.get(r.results.get(d, ""), NA) for d in drugs] + [rendered(r)]
    return row


def npoc(r):
    return [day(r.test_date), POS_NEG.get(r.mtb_result, NA), num(r.signal_value), rendered(r)]


def qft(r):
    return [day(r.test_date), POS_NEG.get(r.interpretation, NA), num(r.nil), num(r.tb1), num(r.tb2),
            num(r.mitogen), rendered(r)]


def wgs(a):
    return [day(a.run_date), val(a.lineage), val(a.sublineage),
            upper(a.get_drug_profile_display()) if a.drug_profile else NA,
            val(a.resistance_mutations.replace("\n", " ")) if a.resistance_mutations else NA, val(a.cluster)]


def columns():
    from apps.diagnostic.models import DST

    drugs = [d for d, _ in DST.DRUGS]
    return [
        # (code, en-têtes, famille de résultats, filtre, fonction)
        ("GNX-RIF", ["Date GNX-RIF", "GNX-RIF", "Resistance RIF", "Date rendu GNX-RIF"],
         "gx", {"assay": "ULTRA"}, gx_ultra),
        ("GNX-XDR", ["Date GNX-XDR", "GNX-XDR"] + [f"GNX-XDR-{d}" for d, _ in XDR_FIELDS] + ["Date rendu GNX-XDR"],
         "gx", {"assay": "XDR"}, gx_xdr),
        ("FLUO-AUR", ["Date FLUO-AUR", "FLUO-AUR", "Quant-FLUO-AUR", "Date rendu FLUO-AUR"],
         "micro", {"method": "FM"}, microscopy),
        ("ZN", ["Date ZN", "ZN", "Quant-ZN", "Date rendu ZN"], "micro", {"method": "ZN"}, microscopy),
        ("Cult-LJ", ["Date Cult-LJ", "Cult-LJ", "Cotation-Cult-LJ", "Date sortie Cult-LJ", "Temps de positivité",
                     "Date rendu Cult-LJ", "Identification"], "culture", {"medium": "LJ"}, culture),
        ("Cult-MGIT", ["Date Cult-MGIT", "Cult-MGIT", "Date sortie Cult-MGIT", "Temps de positivité MGIT",
                       "Date rendu Cult-MGIT", "Identification MGIT"], "culture", {"medium": "MGIT"}, culture),
        ("DST-LJ", ["Date DST-LJ", "Groupe DST-LJ"] + [f"DST-LJ-{d}" for d in drugs] + ["Date rendu DST-LJ"],
         "dst", {"method": "LJ"}, dst(drugs)),
        ("DST-MGIT", ["Date DST-MGIT", "Groupe DST-MGIT"] + [f"DST-MGIT-{d}" for d in drugs]
         + ["Date rendu DST-MGIT"], "dst", {"method": "MGIT"}, dst(drugs)),
        ("NPOC", ["Date NPOC", "NPOC", "Signal NPOC (Tt/Ct)", "Date rendu NPOC"], "npoc", {}, npoc),
        ("QFT", ["Date QFT", "QFT", "QFT-Nil", "QFT-TB1", "QFT-TB2", "QFT-Mitogène", "Date rendu QFT"],
         "qft", {}, qft),
        ("WGS", ["Date WGS", "Lignée", "Sous-lignée", "Profil de résistance WGS", "Mutations de résistance",
                 "Cluster"], "wgs", {}, wgs),
    ]


SAMPLE_HEADERS = ["N° échantillon", "Identifiant externe", "Nom et Prénom", "Date de naissance", "Age", "Sexe",
                  "Adresse", "Région", "Provenance / CDT", "Prescripteur", "Contact Prescripteur", "Hôte",
                  "Type de prélèvement", "Forme", "Aspect", "Volume (mL)", "Date de prélèvement", "Date de réception",
                  "Projet", "Étude", "Cas", "Conforme", "Motif de non-conformité", "Statut VIH", "Statut"]


def sample_values(s):
    p = s.patient
    facility = f"{s.facility.code} — {s.facility.name}" if s.facility else NA
    return [
        s.code, val(p.code if p else ""), val(p.full_name if p else ""), day(p.birth_date if p else None),
        val(p.age if p else None), val(p.get_sex_display() if p and p.sex != "I" else ""),
        val(p.address if p else ""), val(s.facility.region if s.facility else ""), facility, val(s.requester),
        val(s.requester_contact), val(s.host), s.type_display, s.tb_form, val(s.aspect), num(s.volume_ml),
        day(s.collected_at), day(s.received_at), val(s.project.code if s.project else ""),
        val(s.study.code if s.study else ""), val(s.case_display), val(s.conform),
        val(s.non_conformity) if not s.conform else NA,
        val(p.get_hiv_status_display() if p else ""), s.get_status_display(),
    ]


def export_samples(qs):
    from apps.bioinfo.models import Analysis
    from apps.diagnostic.models import DST, Culture, GeneXpertTest, Microscopy, NPOCTest, Quantiferon

    qs = qs.select_related("patient", "facility", "project", "study", "case")
    sources = {
        "gx": GeneXpertTest.objects.order_by("-test_date", "-id"),
        "micro": Microscopy.objects.order_by("-test_date", "-id"),
        "culture": Culture.objects.order_by("-inoculated_on", "-id"),
        "dst": DST.objects.order_by("-test_date", "-id"),
        "npoc": NPOCTest.objects.order_by("-test_date", "-id"),
        "qft": Quantiferon.objects.order_by("-test_date", "-id"),
        "wgs": Analysis.objects.order_by("-run_date", "-id"),
    }
    ids = list(qs.values_list("pk", flat=True))
    results = {key: {} for key in sources}
    for key, rqs in sources.items():
        for r in rqs.filter(sample_id__in=ids):
            results[key].setdefault(r.sample_id, []).append(r)

    cols = columns()
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="echantillons_{timezone.localdate():%Y-%m-%d}.csv"'
    resp.write("﻿")  # BOM UTF-8 : Excel affiche correctement les accents
    w = csv.writer(resp, delimiter=";", lineterminator="\r\n")
    w.writerow(SAMPLE_HEADERS + [h for _, headers, *_ in cols for h in headers])
    for s in qs:
        row = sample_values(s)
        for _, headers, key, match, fn in cols:
            r = latest(results[key].get(s.pk, []), **match)
            row += fn(r) if r else [NA] * len(headers)
        w.writerow(row)
    return resp
