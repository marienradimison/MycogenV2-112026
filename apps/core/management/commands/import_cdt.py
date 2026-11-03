"""Importe la liste des CDT (structures de provenance) depuis les fichiers Excel du PNLT.

    python manage.py import_cdt "Liste 250 CDT 23_08_2022.xlsx" "Nouveaux CDT  2026.xlsx"

Deux formats reconnus automatiquement :
- liste PNLT 2022 : onglets « CODE REGION » + « 18082022 » (CodeCDT, CDT, SSD, id, RegId…)
- liste des nouveaux CDT : colonnes Numero / REGION / DISTRICTS / CSB à accréditer / CODE3
  (cellules région/district fusionnées → valeur reprise de la ligne précédente)

L'import est idempotent : un CDT existant (même code) est mis à jour, jamais dupliqué.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Facility

# Variantes d'orthographe rencontrées → nom de région officiel
REGION_ALIASES = {
    "AMORON I MANIA": "AMORON'I MANIA",
    "AMORON’NY MANIA": "AMORON'I MANIA",
    "AMORON'NY MANIA": "AMORON'I MANIA",
    "AMORON’I MANIA": "AMORON'I MANIA",
    "VAKINAKARATRA": "VAKINANKARATRA",
    "FITOVAVY": "FITOVINANY",
}


def clean(text):
    return re.sub(r"\s+", " ", str(text or "").replace("\xa0", " ")).strip()


def region_name(text):
    name = clean(text).upper()
    return REGION_ALIASES.get(name, name)


def district_name(text):
    return re.sub(r"^SDSP\s+", "", clean(text), flags=re.I)


class Command(BaseCommand):
    help = "Importe/actualise les CDT depuis les fichiers Excel du PNLT."

    def add_arguments(self, parser):
        parser.add_argument("files", nargs="+")
        parser.add_argument("--dry-run", action="store_true", help="Affiche sans enregistrer")

    def handle(self, *args, **opts):
        files = opts["files"]
        try:
            import openpyxl
        except ImportError as exc:
            raise CommandError("openpyxl manquant : pip install -r requirements.txt") from exc

        rows = []
        for path in files:
            wb = openpyxl.load_workbook(path, data_only=True)
            if "CODE REGION" in wb.sheetnames:
                rows += self.read_pnlt_2022(wb, path)
            else:
                rows += self.read_new_cdt(wb, path)

        created = updated = 0
        with transaction.atomic():
            for code, name, district, region, note in rows:
                defaults = {"name": name, "district": district, "region": region,
                            "type": "CDT", "active": True}
                obj = Facility.objects.filter(code=code).first()
                if obj is None:
                    Facility.objects.create(code=code, notes=note, **defaults)
                    created += 1
                else:
                    for k, v in defaults.items():
                        setattr(obj, k, v)
                    obj.save()
                    updated += 1
            if opts["dry_run"]:
                transaction.set_rollback(True)
        verb = "simulés" if opts["dry_run"] else "enregistrés"
        self.stdout.write(self.style.SUCCESS(
            f"{len(rows)} CDT lus : {created} créés, {updated} mis à jour ({verb})."))

    def read_pnlt_2022(self, wb, path):
        regions = {}
        for r in wb["CODE REGION"].iter_rows(min_row=3, values_only=True):
            if isinstance(r[0], int):
                regions[r[0]] = region_name(r[1])
        sheet = "18082022" if "18082022" in wb.sheetnames else "Liste_CDT"
        out = []
        for r in wb[sheet].iter_rows(min_row=3, values_only=True):
            if not r[0] or not r[1]:
                continue
            out.append((clean(r[0]), clean(r[1]), district_name(r[2]), regions.get(r[4], ""),
                        "Liste PNLT 23/08/2022"))
        self.stdout.write(f"  {path} : {len(out)} CDT (onglet {sheet})")
        return out

    def read_new_cdt(self, wb, path):
        ws = wb.worksheets[0]
        header_row = None
        for i, r in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=True), start=1):
            if r and any(clean(c).upper() == "CODE3" for c in r if c):
                header_row = i
                cols = {clean(c).upper(): j for j, c in enumerate(r) if c}
                break
        if header_row is None:
            raise CommandError(f"{path} : colonne CODE3 introuvable.")
        i_reg, i_dist, i_code = cols["REGION"], cols["DISTRICTS"], cols["CODE3"]
        i_name = next(j for k, j in cols.items() if k.startswith("CSB"))
        region = district = ""
        out = []
        for r in ws.iter_rows(min_row=header_row + 1, values_only=True):
            if not isinstance(r[0], int) or not r[i_code]:
                continue
            region = region_name(r[i_reg]) if r[i_reg] else region
            district = district_name(r[i_dist]) if r[i_dist] else district
            out.append((clean(r[i_code]), clean(r[i_name]), district, region, "Nouveaux CDT 2026"))
        self.stdout.write(f"  {path} : {len(out)} nouveaux CDT")
        return out
