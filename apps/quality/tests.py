from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Room

from .models import Equipment, RoomAccess


class QualityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_mycogen", verbosity=0)
        cls.rq = User.objects.create_user("qualite", password="x", first_name="Rijanirina", last_name="R")
        cls.rq.groups.add(Group.objects.get(role_code__code="RQ/CQ"))
        cls.tech = User.objects.create_user("tech", password="x", first_name="Marien")
        cls.room = Room.objects.get(zone="7")

    def setUp(self):
        self.client.force_login(self.rq)

    def test_next_dates_computed(self):
        e = Equipment.objects.create(room=self.room, name="PSM n°2", category="PSM", maintenance_interval_months=12,
                                     last_maintenance=date(2026, 1, 31), calibration_interval_months=6,
                                     last_calibration=date(2025, 8, 31))
        self.assertEqual(e.next_maintenance, date(2027, 1, 31))
        self.assertEqual(e.next_calibration, date(2026, 2, 28))  # fin de mois gérée
        self.assertEqual(e.calibration_state, "overdue")
        self.assertEqual(e.alert, "danger")

    def test_access_rules(self):
        today = timezone.localdate()
        a = RoomAccess.objects.create(room=self.room, user=self.tech, expires_on=today + timedelta(days=10))
        self.assertEqual(a.state, "soon")
        # doublon d'accès actif refusé via le formulaire
        r = self.client.post(reverse("quality:access_create"), {
            "room": self.room.pk, "user": self.tech.pk, "level": "FULL", "granted_on": str(today)})
        self.assertContains(r, "déjà un accès actif")
        # personne sans compte
        r = self.client.post(reverse("quality:access_create"), {
            "room": self.room.pk, "person_name": "Technicien Biomérieux", "level": "MAINT", "granted_on": str(today)})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(RoomAccess.objects.get(person_name="Technicien Biomérieux").granted_by, self.rq)
        # ni utilisateur ni nom → erreur
        r = self.client.post(reverse("quality:access_create"), {"room": self.room.pk, "level": "FULL",
                                                                "granted_on": str(today)})
        self.assertContains(r, "Choisissez un utilisateur")

    def test_monitoring_and_plan_panel(self):
        today = timezone.localdate()
        Equipment.objects.create(room=self.room, name="Centrifugeuse", status="DOWN")
        Equipment.objects.create(room=self.room, name="Incubateur", next_maintenance=today - timedelta(days=3))
        RoomAccess.objects.create(room=self.room, user=self.tech, expires_on=today - timedelta(days=1))
        html = self.client.get(reverse("quality:monitoring")).content.decode()
        for text in ("Centrifugeuse", "Incubateur", "Marien"):
            self.assertIn(text, html)
        plan = self.client.get(reverse("core:floorplan")).content.decode()
        self.assertIn("Centrifugeuse", plan)
        self.assertIn("expir", plan)  # « expiré » (échappé en JSON dans les données de la fiche)
        room_page = self.client.get(self.room.get_absolute_url()).content.decode()
        self.assertIn("Incubateur", room_page)
        for url in (reverse("quality:equipment_list"), reverse("quality:access_list"),
                    reverse("quality:equipment_create") + f"?room={self.room.pk}"):
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_sgq_reserved_to_sl_rq_cds(self):
        self.tech.groups.add(Group.objects.get(role_code__code="TL"))
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(reverse("quality:equipment_list")).status_code, 403)
        sl = User.objects.create_user("sl", password="x")
        sl.groups.add(Group.objects.get(role_code__code="SL"))
        self.client.force_login(sl)
        self.assertEqual(self.client.get(reverse("quality:equipment_create")).status_code, 200)


class SGQTests(TestCase):
    """SGQ : statistiques mensuelles et indicateurs de performance (modèle Suivi_performance_labo)."""

    @classmethod
    def setUpTestData(cls):
        from datetime import datetime

        from apps.core.models import Patient, Sample
        from apps.diagnostic.models import DST, Culture, GeneXpertTest, Microscopy

        call_command("init_mycogen", verbosity=0)
        cls.rq = User.objects.create_user("qualite", password="x")
        cls.rq.groups.add(Group.objects.get(role_code__code="RQ/CQ"))
        tz = timezone.get_current_timezone()
        cls.year = timezone.localdate().year - 1
        march = datetime(cls.year, 3, 10, 9, tzinfo=tz)

        def sample(stype="SPUTUM", reason="DIAG", **kw):
            p = Patient.objects.create(last_name="Test", first_name="P")
            return Sample.objects.create(patient=p, sample_type=stype, reason=reason, received_at=march, **kw)

        a, b, c = sample(), sample(), sample("PUS")
        sample(conform=False, non_conformity="Tube fuité")
        fu = sample(reason="FU")
        # GNX-RIF : a MTB+ RIF-R, b MTB-, c invalide, fu MTB+ (suivi : hors DT)
        GeneXpertTest.objects.create(sample=a, mtb_result="HIGH", rif_result="DETECTED")
        GeneXpertTest.objects.create(sample=b, mtb_result="NOT_DETECTED")
        GeneXpertTest.objects.create(sample=c, mtb_result="ERROR")
        GeneXpertTest.objects.create(sample=fu, mtb_result="LOW", rif_result="NOT_DETECTED")
        GeneXpertTest.objects.create(sample=a, assay="XDR", mtb_result="HIGH", inh_result="DETECTED",
                                     fq_result="DETECTED", amk_result="DETECTED", kan_result="NOT_DETECTED",
                                     cap_result="NOT_DETECTED", eto_result="NOT_DETECTED")
        Microscopy.objects.create(sample=a, grade="2+")
        Microscopy.objects.create(sample=b, grade="SCANTY")
        Culture.objects.create(sample=a, medium="LJ", inoculated_on=march.date(), result="POSITIVE",
                               identification="MTBC")
        Culture.objects.create(sample=b, medium="LJ", inoculated_on=march.date(), result="CONTAMINATED")
        Culture.objects.create(sample=c, medium="LJ", inoculated_on=march.date(), result="POSITIVE",
                               identification="NTM")
        Culture.objects.create(sample=fu, medium="LJ", inoculated_on=march.date())
        DST.objects.create(sample=a, panel="FIRST", results={"STR": "S", "INH": "R", "RIF": "R", "EMB": "S",
                                                             "PZA": "S"})
        DST.objects.create(sample=a, panel="SECOND", results={"OFX": "R", "LEV": "R", "KAN": "R", "AMK": "S"})
        DST.objects.create(sample=b, panel="FIRST", results={"STR": "R", "INH": "S", "RIF": "S", "EMB": "S",
                                                             "PZA": "S"})

    def setUp(self):
        self.client.force_login(self.rq)

    def rows(self, data, key):
        table = next(t for t in [*data["tables"], data["global"]] if t["key"] == key)
        return {r["label"]: r for r in table["rows"] if r["kind"] != "head"}

    def test_method_tables(self):
        from .sgq import compute

        data = compute(self.year)
        s = self.rows(data, "samples")
        self.assertEqual(s["Total prélèvements reçus"]["values"][2], 5)
        self.assertEqual((s["Pulmonaire"]["total"], s["Extra-pulmonaire"]["total"], s["Prélèvements rejetés"]["total"]),
                         (4, 1, 1))
        g = self.rows(data, "gnx")
        self.assertEqual([g[k]["total"] for k in ("GNX-RIF réalisés", "GNX-RIF valides", "MTB détecté",
                                                  "MTB non détecté", "RIF détectée", "Invalid, error, no result")],
                         [4, 3, 2, 1, 1, 1])
        self.assertEqual(g["% MTB POSITIF"]["total"], 66.7)     # 2 / 3 valides
        self.assertEqual(g["% RIF-R"]["total"], 50.0)           # 1 / 2 MTB détectés
        self.assertEqual(g["% test invalid"]["total"], 25.0)    # 1 / 4 réalisés
        lj = self.rows(data, "cult_lj")
        self.assertEqual([lj[k]["total"] for k in ("Cult-LJ réalisées", "CMTB +", "CMTB -", "Contamination (RTT)",
                                                   "En cours")], [4, 1, 1, 1, 1])
        dst = self.rows(data, "dst_mgit")
        self.assertEqual(dst["Multi-résistant (TB-MR)"]["total"], 1)
        self.assertEqual(dst["Mono-STR"]["total"], 1)
        self.assertEqual(dst["TB-XDR"]["total"], 1)             # FLQ (OFX/LEV) R + KAN R
        self.assertEqual(dst["% TB-MR"]["total"], 50.0)
        x = self.rows(data, "xdr")
        self.assertEqual(x["TB-XDR"]["total"], 1)               # FLQ + AMK détectés
        self.assertEqual(x["Mono-INH"]["total"], 0)             # 3 résistances : pas de monorésistance
        cc = self.rows(data, "cc_smear")
        self.assertEqual(cc["GNX+/smear+"]["total"], (1, 100.0))
        self.assertEqual(cc["GNX-/smear+"]["total"], (1, 100.0))
        # mois à venir vides, mois passés renseignés
        self.assertNotEqual(s["Total prélèvements reçus"]["values"][11], "")

    def test_global_indicators(self):
        from .sgq import compute

        dt = self.rows(compute(self.year), "global")
        self.assertEqual(dt["DT-1"]["total"], (3, None))         # suivi exclu
        self.assertEqual(dt["DT-2"]["total"], (1, 33.3))
        self.assertEqual(dt["DT-3"]["total"], (1, 33.3))
        self.assertEqual(dt["DT-4"]["total"][0], 2)               # a (GNX+) et b (frottis +)
        self.assertEqual(dt["DT-6"]["total"], (1, 50.0))          # MDR / 2 DST 1ère ligne
        self.assertEqual(dt["DT-7"]["total"], (1, 100.0))
        self.assertEqual(dt["DT-9"]["total"], (1, 100.0))
        self.assertEqual(dt["DT-10"]["total"], (1, 100.0))

    def test_page_export_and_permissions(self):
        url = reverse("quality:sgq")
        for tab in ("methodes", "concordances", "globale", "delais", "definitions"):
            r = self.client.get(url, {"annee": self.year, "onglet": tab})
            self.assertEqual(r.status_code, 200)
        self.assertContains(self.client.get(url, {"annee": self.year}), "% MTB POSITIF")
        self.assertContains(self.client.get(url, {"onglet": "definitions"}), "Extensive Drug Resistant")
        raw = self.client.get(url, {"annee": self.year, "export": "csv"}).content
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn("Prélèvements rejetés".encode(), raw)
        tech = User.objects.create_user("tl", password="x")
        tech.groups.add(Group.objects.get(role_code__code="TL"))
        self.client.force_login(tech)
        self.assertEqual(self.client.get(url).status_code, 403)
