"""Interprétation des messages d'automates et création des résultats dans le LIMS.

Principe de sécurité : chaque message est d'abord enregistré tel quel (InstrumentMessage).
Un résultat n'est créé que si l'échantillon est identifié sans ambiguïté ; il arrive
toujours au statut « Saisi » et doit être validé par un biologiste.
"""
import logging
import re

from django.db import close_old_connections, transaction
from django.utils import timezone

from apps.core.crud import log as audit_log
from apps.core.models import Sample

from . import astm
from .models import InstrumentMessage

log = logging.getLogger("mycogen.instruments")


def find_sample(ref):
    ref = (ref or "").strip()
    if not ref:
        return None
    return (Sample.objects.filter(code__iexact=ref).first()
            or Sample.objects.filter(external_id__iexact=ref).first())


def split_groups(records):
    """Regroupe les enregistrements par demande : [(O, [R…], [C…])] + requêtes Q."""
    groups, queries, current = [], [], None
    for rec in records:
        if rec.type == "O":
            current = [rec, [], []]
            groups.append(current)
        elif rec.type == "R" and current:
            current[1].append(rec)
        elif rec.type == "C" and current:
            current[2].append(rec)
        elif rec.type == "Q":
            queries.append(rec)
    return groups, queries


def group_text(o, results, comments):
    return "\r".join("|".join(r[1:]) for r in [o, *results, *comments])


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def handle_astm(instrument, text):
    """Traite une transmission ASTM complète. Retourne le message de réponse éventuel."""
    close_old_connections()
    try:
        instrument.last_seen = timezone.now()
        instrument.save(update_fields=["last_seen"])
        records = astm.parse_message(text)
        groups, queries = split_groups(records)
        reply = None

        for q in queries:
            ref = next((c for c in q.components(3) if c), "")
            InstrumentMessage.objects.create(
                instrument=instrument, kind="QUERY", status="INFO", sample_ref=ref, sample=find_sample(ref),
                summary="Requête hôte : test en préparation / démarré", raw="|".join(q[1:]))
            if instrument.reply_to_queries:
                reply = astm.no_information_reply(q)

        for o, results, comments in groups:
            raw = group_text(o, results, comments)
            msg = InstrumentMessage(instrument=instrument, kind="RESULT" if results else "OTHER",
                                    sample_ref=o.component(3, 0), raw=raw)
            msg.save()
            if InstrumentMessage.objects.filter(instrument=instrument, raw_hash=msg.raw_hash,
                                                status="IMPORTED").exclude(pk=msg.pk).exists():
                msg.status, msg.summary = "DUPLICATE", "Message déjà reçu et importé"
                msg.save()
                continue
            process(msg, records=(o, results, comments))

        if not groups and not queries:
            InstrumentMessage.objects.create(instrument=instrument, kind="OTHER", status="INFO",
                                             summary="Message sans résultat", raw=text)
        return reply
    finally:
        close_old_connections()


def process(msg, records=None, sample=None):
    """(Ré)interprète un message enregistré. `sample` force l'échantillon (association manuelle)."""
    if records is None:
        parsed = astm.parse_message(msg.raw)
        groups, _ = split_groups(parsed)
        if not groups:
            msg.status, msg.detail = "ERROR", "Aucun enregistrement O (demande) dans le message."
            msg.save()
            return msg
        records = groups[0]
    o, results, comments = records

    sample = sample or find_sample(msg.sample_ref)
    msg.sample = sample
    if sample is None:
        msg.status = "UNMATCHED"
        msg.summary = f"Échantillon « {msg.sample_ref} » introuvable dans Mycogen"
        msg.save()
        return msg

    handler = {"GENEXPERT": import_genexpert, "MGIT": import_mgit}.get(msg.instrument.kind)
    if handler is None:
        msg.status, msg.summary = "NEW", "Pas d'interprétation automatique pour cet automate"
        msg.save()
        return msg
    try:
        with transaction.atomic():
            obj, summary = handler(msg, sample, o, results)
            msg.status, msg.summary, msg.detail = "IMPORTED", summary[:255], ""
            msg.result_model, msg.result_id = obj._meta.label, obj.pk
            msg.save()
            audit_log(None, "CREATE", obj, {"source": f"automate {msg.instrument.name}"})
    except Exception as exc:  # le message reste consultable et ré-importable
        log.exception("Import impossible du message %s", msg.pk)
        msg.status, msg.detail = "ERROR", f"{type(exc).__name__} : {exc}"
        msg.save()
    return msg


# ---------------------------------------------------------------------------
# GeneXpert (Xpert MTB/RIF Ultra, MTB/XDR)
# ---------------------------------------------------------------------------

LEVELS = [("VERY LOW", "VERY_LOW"), ("VERY HIGH", "VERY_HIGH"), ("TRACE", "TRACE"), ("LOW", "LOW"),
          ("MEDIUM", "MEDIUM"), ("HIGH", "HIGH")]
DRUGS = [  # (mots-clés dans le résultat, champ du modèle)
    (("RIF",), "rif_result"),
    (("INH",), "inh_result"),
    (("FLQ", "FQ ", "FLUOROQUINOLONE"), "fq_result"),
    (("AMK", "AMIKACIN"), "amk_result"),
    (("KAN", "KANAMYCIN"), "kan_result"),
    (("CAP", "CAPREOMYCIN"), "cap_result"),
    (("ETH", "ETHIONAMIDE"), "eto_result"),
]


def detection(text):
    if "NOT DETECTED" in text:
        return "NOT_DETECTED"
    if "INDETERMINATE" in text:
        return "INDETERMINATE"
    if "DETECTED" in text:
        return "DETECTED"
    return None


def classify_genexpert(values):
    """Convertit les libellés GeneXpert (« MTB DETECTED MEDIUM », « Rif Resistance NOT DETECTED »…)."""
    out = {}
    for value in values:
        for part in re.split(r"[;\n]", value.upper()):
            part = part.strip()
            if not part:
                continue
            if "RESISTANCE" in part:
                det = detection(part)
                for keys, field in DRUGS:
                    if det and any(k in part + " " for k in keys):
                        out[field] = det
                        break
            elif "MTB" in part:
                if "NOT DETECTED" in part:
                    out["mtb_result"] = "NOT_DETECTED"
                elif "DETECTED" in part:
                    out["mtb_result"] = next((code for word, code in LEVELS if word in part), "DETECTED")
            elif part.startswith("INVALID"):
                out.setdefault("mtb_result", "INVALID")
            elif part.startswith("ERROR"):
                out.setdefault("mtb_result", "ERROR")
            elif part.startswith("NO RESULT"):
                out.setdefault("mtb_result", "NO_RESULT")
    return out


def import_genexpert(msg, sample, o, results):
    from apps.diagnostic.models import GeneXpertTest

    test_text = " ".join([o.get(5)] + [r.get(3) for r in results]).upper()
    assay = "XDR" if "XDR" in test_text else "ULTRA"
    values = [r.get(4).replace(r.d["component"], " ") for r in results]
    fields = classify_genexpert(values)
    if "mtb_result" not in fields:
        raise ValueError(f"Résultat MTB non reconnu dans : {values}")

    first = results[0] if results else o
    completed = astm.astm_datetime(first.get(13)) or astm.astm_datetime(first.get(12))
    operator = first.component(11, 0)
    module = " ".join(c for c in first.components(14) if c)[:50] or msg.instrument.name
    probes = [f"{r.component(3, 6) or r.get(3)}={r.component(4, 0)}"
              for r in results if re.fullmatch(r"[\d.]+", r.component(4, 0) or "")]

    obj = msg.result if msg.result is not None and not msg.result.is_validated else GeneXpertTest(sample=sample)
    obj.sample = sample
    obj.assay = assay
    obj.instrument = module
    obj.test_date = completed.date() if completed else timezone.localdate()
    for f in ("rif_result", "inh_result", "fq_result", "amk_result", "kan_result", "cap_result", "eto_result"):
        setattr(obj, f, fields.get(f, "NA"))
    obj.mtb_result = fields["mtb_result"]
    obj.comment = "\n".join(filter(None, [
        f"Importé automatiquement depuis {msg.instrument.name}",
        f"Opérateur automate : {operator}" if operator else "",
        f"Ct : {', '.join(probes)}" if probes else "",
    ]))
    obj.save()
    return obj, f"{obj.get_assay_display()} : {obj.get_mtb_result_display()}" + (
        f" · RIF {obj.get_rif_result_display()}" if obj.rif_result != "NA" else "")


# ---------------------------------------------------------------------------
# BD MGIT 960 / EpiCenter
# ---------------------------------------------------------------------------

def parse_ttp_days(value):
    """TTP « 12d 5h », « 12/05 » (jours/heures) ou nombre d'heures → jours (1 décimale)."""
    value = (value or "").strip().lower()
    m = re.search(r"(\d+)\s*d\D*(\d+)\s*h", value) or re.fullmatch(r"(\d+)\s*/\s*(\d+)", value)
    if m:
        return round(int(m.group(1)) + int(m.group(2)) / 24, 1)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*h?", value)
    if m:
        return round(float(m.group(1)) / 24, 1)
    return None


def import_mgit(msg, sample, o, results):
    from decimal import Decimal

    from apps.diagnostic.models import Culture

    status = ttp = None
    for r in results:
        test = " ".join(r.components(3)).upper()
        value = " ".join(r.components(4)).upper()
        if "TTP" in test:
            ttp = parse_ttp_days(r.component(4, 0))
            continue
        if "POS" in value:
            status = "POSITIVE"
        elif "NEG" in value:
            status = "NEGATIVE"
        elif "ONGOING" in value or "PROGRESS" in value or "IN PROTOCOL" in value:
            status = status or "PENDING"
        if ttp is None:
            for c in r.components(4)[1:]:
                ttp = ttp or parse_ttp_days(c)
    if status is None:
        raise ValueError("Statut MGIT (positif/négatif/en cours) non reconnu.")

    tube = o.component(4, 0) or o.component(3, 1)
    qs = Culture.objects.filter(sample=sample, medium="MGIT").exclude(result_status="VALIDATED")
    obj = (msg.result if msg.result is not None and not msg.result.is_validated else None) \
        or (tube and qs.filter(tube_number=tube).first()) or qs.filter(result="PENDING").first()
    if obj is None:
        started = astm.astm_datetime(results[0].get(12)) if results else None
        obj = Culture(sample=sample, medium="MGIT", tube_number=tube or "",
                      inoculated_on=started.date() if started else timezone.localdate())
    obj.result = status
    if status != "PENDING":
        obj.result_date = timezone.localdate()
    if ttp is not None:
        obj.ttp_days = Decimal(str(ttp))
    note = f"Mis à jour automatiquement depuis {msg.instrument.name}"
    if note not in obj.comment:
        obj.comment = (obj.comment + "\n" + note).strip()
    obj.save()
    return obj, f"MGIT : {obj.get_result_display()}" + (f" · TTP {obj.ttp_days} j" if obj.ttp_days else "")


# ---------------------------------------------------------------------------
# Dossiers d'export (Pluslife…)
# ---------------------------------------------------------------------------

def handle_file(instrument, filename, content):
    close_old_connections()
    try:
        instrument.last_seen = timezone.now()
        instrument.save(update_fields=["last_seen"])
        msg = InstrumentMessage(instrument=instrument, kind="RESULT", raw=content,
                                summary=f"Fichier {filename}")
        msg.save()
        if InstrumentMessage.objects.filter(instrument=instrument, raw_hash=msg.raw_hash).exclude(pk=msg.pk).exists():
            msg.status = "DUPLICATE"
        else:
            msg.status = "NEW"
            msg.detail = "Format d'export à configurer : interprétation automatique non encore disponible."
        msg.save()
        return msg
    finally:
        close_old_connections()
