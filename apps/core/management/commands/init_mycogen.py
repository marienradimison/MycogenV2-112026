"""Initialise les rôles (groupes + permissions) et les référentiels de base.

    python manage.py init_mycogen            # rôles + pipelines par défaut
    python manage.py init_mycogen --demo     # + jeu de données de démonstration
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

ALL = ("view", "add", "change", "delete")
RW = ("view", "add", "change")

L = ("view",)
LM = ("view", "change")
LA = ("view", "add")

# Rôles = jeux de permissions (un utilisateur peut en cumuler plusieurs).
# code -> (libellé, {app_label: {modèle: actions}})   ("*" = tous les modèles de l'app ; "extra" = permissions spéciales)
ROLES = {
    "TL": ("Technicien(ne) de Laboratoire", {
        "core": {"patient": RW, "sample": RW, "facility": L, "room": L},
        "diagnostic": {"*": RW},
        "research": {"project": L, "*": RW},
        "biobank": {"*": RW},
        "instruments": {"instrument": L, "instrumentmessage": LM},
        "quality": {"equipment": L, "roomaccess": L},
        "stock": {"article": L, "lot": L, "movement": LA},
    }),
    "SL": ("Surveillant(e) de Laboratoire", {
        "core": {"patient": RW, "sample": RW, "facility": L, "room": L, "analysiscode": L},
        "diagnostic": {"*": ALL},
        "research": {"*": L},
        "biobank": {"*": ALL},
        "instruments": {"*": RW},
        "quality": {"*": L},
        "stock": {"*": ALL},
        "extra": ["core.view_activitylog", "quality.view_sgq"],
    }),
    "MB": ("Médecin Biologiste", {
        "core": {"*": ALL},
        "diagnostic": {"*": ALL},
        "research": {"*": ALL},
        "biobank": {"*": ALL},
        "bioinfo": {"*": L},
        "instruments": {"*": ALL},
        "quality": {"*": L},
        "stock": {"*": L},
        "extra": ["core.validate_results", "core.view_activitylog", "quality.view_sgq"],
    }),
    "AS": ("Agent de Saisie", {
        "core": {"patient": RW, "sample": RW, "facility": L, "room": L},
        "research": {"project": L, "study": L, "projectcase": L},
    }),
    "RSR": ("Researcher", {
        "core": {"patient": L, "sample": RW, "facility": L, "room": L},
        "diagnostic": {"*": L},
        "research": {"*": ALL},
        "biobank": {"*": RW},
        "bioinfo": {"*": ALL},
        "stock": {"article": L, "lot": L},
    }),
    "RQ/CQ": ("Responsable Qualité / Correspondant Qualité", {
        "core": {"room": LM, "facility": L, "sample": L},
        "quality": {"*": ALL},
        "instruments": {"instrument": L},
        "biobank": {"storageunit": L},
        "diagnostic": {"temperaturelog": L},
        "stock": {"article": L, "lot": L, "movement": L},
        "extra": ["core.view_activitylog", "quality.view_sgq"],
    }),
    "AL": ("Agent de Laboratoire", {
        "core": {"sample": L, "room": L},
        "diagnostic": {"culture": L, "culturetube": L, "temperaturelog": LA},
        "quality": {"equipment": L},
        "stock": {"article": L, "lot": L, "movement": LA},
    }),
}
# Anciens rôles → nouveaux (les utilisateurs sont transférés, puis l'ancien groupe est supprimé)
LEGACY = {"Réception": "AS", "Technicien": "TL", "Biologiste": "MB", "Chercheur": "RSR",
          "Gestionnaire biobanque": "SL", "Bioinformaticien": "RSR", "Responsable matériel & qualité": "RQ/CQ"}

class Command(BaseCommand):
    help = "Crée les rôles Mycogen et (option --demo) des données de démonstration."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true", help="Ajoute des données fictives de démonstration")

    @transaction.atomic
    def handle(self, *args, **opts):
        from django.apps import apps

        from apps.core.models import AnalysisCode

        for order, (code, (label, spec)) in enumerate(ROLES.items(), start=1):
            group, _ = Group.objects.get_or_create(name=label)
            AnalysisCode.objects.update_or_create(code=code, defaults={
                "category": "ROLE", "meaning": label, "group": group, "kind": "", "method": "",
                "requestable": False, "order": 500 + order, "active": True})
            role = f"{code} — {label}"
            perms = []
            for app_label, models in spec.items():
                if app_label == "extra":
                    for p in models:
                        a, code = p.split(".")
                        perms.append(Permission.objects.get(content_type__app_label=a, codename=code))
                    continue
                default = models.get("*")
                for model in apps.get_app_config(app_label).get_models():
                    name = model._meta.model_name
                    actions = models.get(name, default)
                    if name == "activitylog" or not actions:
                        continue
                    for act in actions:
                        perms.append(Permission.objects.get(content_type__app_label=app_label,
                                                            codename=f"{act}_{name}"))
            group.permissions.set(perms)
            self.stdout.write(f"  rôle « {role} » : {len(perms)} permissions")

        for old_name, code in LEGACY.items():
            old = Group.objects.filter(name=old_name).first()
            if old:
                new = Group.objects.get(name=ROLES[code][0])
                for user in old.user_set.all():
                    user.groups.add(new)
                old.delete()
                self.stdout.write(f"  ancien rôle « {old_name} » remplacé par {code}")

        from apps.bioinfo.models import Pipeline
        for name, version, kind, db in [
            ("TB-Profiler", "6.6", "Profil de résistance & lignée", "tbdb (catalogue OMS 2023)"),
            ("MTBseq", "1.1", "Variants, phylogénie, clusters", ""),
            ("Deeplex Myc-TB", "1.6", "tNGS — résistance", "Genoscreen"),
        ]:
            Pipeline.objects.get_or_create(name=name, version=version,
                                           defaults={"tool_type": kind, "database_version": db})
        self.stdout.write(self.style.SUCCESS("Rôles et référentiels initialisés."))

        if opts["demo"]:
            self.demo()

    def demo(self):
        from apps.biobank.models import BiobankItem, StorageBox, StorageUnit
        from apps.core.models import Facility, Patient, Sample
        from apps.diagnostic.models import Culture, GeneXpertTest, Microscopy, Quantiferon
        from apps.research.models import Project, SequencingLibrary, SequencingRun

        if Patient.objects.exists():
            self.stdout.write("Des patients existent déjà : données de démo non ajoutées.")
            return
        rnd = random.Random(42)
        now = timezone.now()
        facs = [Facility.objects.create(code=c, name=n, region=r, type=t) for c, n, r, t in [
            ("CDT-ANT", "CDT Antananarivo Renivohitra", "Analamanga", "CDT"),
            ("CHU-JRB", "CHU Joseph Raseta Befelatanana", "Analamanga", "CHU"),
            ("CDT-TMV", "CDT Toamasina", "Atsinanana", "CDT"),
            ("CDT-MHJ", "CDT Mahajanga", "Boeny", "CDT"),
        ]]
        proj = Project.objects.create(code="TB-GEN", title="Génomique de M. tuberculosis à Madagascar",
                                      principal_investigator="Investigateur principal", status="ACTIVE",
                                      funder="—", start_date=now.date() - timedelta(days=400))
        names = ["RAKOTO", "RABE", "RASOA", "RANDRIA", "RAZAFY", "RAHARISON", "ANDRIAMANANA", "RAVELO"]
        firsts = ["Jean", "Hery", "Lalao", "Fara", "Tiana", "Nirina", "Mamy", "Voahangy"]
        unit = StorageUnit.objects.create(name="CONG-80-01", type="-80", location="Salle P3")
        box = StorageBox.objects.create(unit=unit, name="BOX-001", shelf="1", rack="A", content="Souches")
        run = SequencingRun.objects.create(run_id="ONT-2026-001", technology="WGS", platform="ONT_GRIDION",
                                           project=proj, library_kit="SQK-RBK114.24", status="DONE")
        pos = 0
        for i in range(24):
            p = Patient.objects.create(last_name=rnd.choice(names), first_name=rnd.choice(firsts),
                                       sex=rnd.choice("MF"), age_years=rnd.randint(16, 70),
                                       district="Antananarivo", hiv_status=rnd.choice(["NEG", "NEG", "INC", "POS"]),
                                       tb_history=rnd.choice(["NEW", "NEW", "REL"]), research_consent=rnd.random() < .6)
            s = Sample.objects.create(patient=p, facility=rnd.choice(facs), sample_type="SPUTUM",
                                      aspect=rnd.choice(["Muqueux", "Muco-purulent", "Salivaire"]),
                                      received_at=now - timedelta(days=rnd.randint(0, 28), hours=rnd.randint(0, 8)),
                                      requested_analyses=["GNX-RIF", "FLUO-AUR", "Cult-MGIT"],
                                      status=rnd.choice(["RECEIVED", "IN_PROGRESS", "COMPLETED"]))
            mtb = rnd.choice(["NOT_DETECTED", "NOT_DETECTED", "LOW", "MEDIUM", "HIGH", "TRACE"])
            pos_ = mtb != "NOT_DETECTED"
            x = GeneXpertTest.objects.create(sample=s, assay="ULTRA", mtb_result=mtb,
                                             rif_result=("DETECTED" if pos_ and rnd.random() < .2 else
                                                         "NOT_DETECTED") if pos_ else "NA",
                                             test_date=s.received_at.date())
            Microscopy.objects.create(sample=s, method="FM", grade=rnd.choice(["1+", "2+", "SCANTY"]) if pos_ else "NEG",
                                      test_date=s.received_at.date())
            c = Culture.objects.create(sample=s, medium="MGIT", inoculated_on=s.received_at.date(),
                                       result=rnd.choice(["PENDING", "POSITIVE"]) if pos_ else "NEGATIVE")
            if c.result == "POSITIVE":
                c.result_date = c.inoculated_on + timedelta(days=rnd.randint(5, 20))
                c.identification = "MTBC"
                c.save()
                pos += 1
                iso = BiobankItem.objects.create(item_type="ISOLATE", sample=s, project=proj, box=box,
                                                 position=f"{'ABCDEFGHI'[(pos - 1) // 9]}{(pos - 1) % 9 + 1}",
                                                 quantity=1, unit="vial")
                dna = BiobankItem.objects.create(item_type="DNA", sample=s, parent=iso, project=proj,
                                                 quantity=50, unit="uL", concentration=Decimal("35.2"))
                SequencingLibrary.objects.create(run=run, sample=s, dna=dna, library_id=f"LIB-{s.code}",
                                                 barcode=f"RB{pos:02d}", mean_depth=Decimal(rnd.randint(40, 180)),
                                                 coverage_pct=Decimal("98.7"), qc_pass=True)
            if i % 4 == 0:
                x.result_status = "VALIDATED"
                x.validated_at = now
                x.save()
            if i % 6 == 0:
                Quantiferon.objects.create(sample=s, nil=Decimal("0.05"), tb1=Decimal(str(rnd.choice([0.1, 1.2]))),
                                           tb2=Decimal("0.3"), mitogen=Decimal("9.5"))
        self.stdout.write(self.style.SUCCESS("Données de démonstration créées (24 patients)."))
