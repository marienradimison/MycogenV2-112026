from decimal import Decimal as D

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Patient, Sample

from .models import Microscopy, QFTRun, Quantiferon

# Plaque de la fiche 26-5483 (DO des standards et de l'échantillon)
STANDARDS = {"s1_od1": D("1.005"), "s1_od2": D("1.005"), "s2_od1": D("0.290"), "s2_od2": D("0.284"),
             "s3_od1": D("0.079"), "s3_od2": D("0.079"), "s4_od1": D("0.007"), "s4_od2": D("0.007")}


class QuantiferonGeneratorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_mycogen", verbosity=0)
        cls.admin = User.objects.create_superuser("adm", "a@example.org", "x", first_name="Marien")
        p = Patient.objects.create(last_name="Ranaivoson", first_name="Francois", code="P-TASA-008")
        cls.sample = Sample.objects.create(code="26-5483", patient=p, requester="Dr Test")
        cls.plate = QFTRun.objects.create(run_id="QFT-2026-11-04", operator=cls.admin, kit_lot="58108959", **STANDARDS)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_curve_and_conversion_match_qiagen_sheet(self):
        curve = self.plate.curve
        self.assertTrue(curve.valid)
        self.assertAlmostEqual(curve.slope, 0.9173, places=2)
        q = Quantiferon.objects.create(sample=self.sample, run=self.plate, od_nil="0,031", od_tb1="0.248",
                                       od_tb2="0.178", od_mitogen="OVER")
        self.assertEqual((q.nil, q.tb1, q.tb2), (D("0.09"), D("0.86"), D("0.60")))
        self.assertGreater(q.mitogen, 10)
        self.assertEqual(q.od_over, "mitogen")
        self.assertEqual(q.interpretation, "POS")
        self.assertEqual(q.kit_lot, "58108959")                       # lot de la plaque

    def test_batch_entry_sheet_and_result_view(self):
        url = reverse("diagnostic:qftrun_add_results", args=[self.plate.pk])
        r = self.client.post(url, {"sample": ["26-5483", "99-9999", ""],
                                   "od_nil": ["0.031", "0.05", ""], "od_tb1": ["0.248", "0.1", ""],
                                   "od_tb2": ["0.178", "0.1", ""], "od_mitogen": [">4", "1.2", ""]}, follow=True)
        self.assertContains(r, "1 résultat(s) ajouté(s)")
        self.assertContains(r, "99-9999 : échantillon introuvable")
        q = Quantiferon.objects.get(sample=self.sample, run=self.plate)
        sheet = self.client.get(reverse("diagnostic:quantiferon_sheet", args=[q.pk])).content.decode()
        for text in ("Résultats QuantiFERONS", "Test ELISA valide", "RANAIVOSON FRANCOIS P-TASA-008", "0,86",
                     "&gt; 10#", "&gt; 10¶", "POSITIF", "Réussi", "4,000", "La valeur OD saisie est non numérique"):
            self.assertIn(text, sheet)
        self.assertEqual(self.client.get(reverse("diagnostic:qftrun_sheets", args=[self.plate.pk])).status_code, 200)
        run_page = self.client.get(self.plate.get_absolute_url())
        self.assertContains(run_page, "Test ELISA valide")
        # correction d'une DO de standard : résultats non validés recalculés
        self.plate.s1_od1 = self.plate.s1_od2 = D("1.200")
        self.plate.save()
        q.refresh_from_db()
        self.assertNotEqual(q.tb1, D("0.86"))
        # aperçu du résultat (modèle commun) avec lien vers la fiche
        page = self.client.get(q.get_absolute_url())
        self.assertContains(page, "Historique / Traçabilité")
        self.assertContains(page, "Fiche de résultats QFT")

    def test_manual_iu_entry_still_possible(self):
        r = self.client.post(reverse("diagnostic:quantiferon_create"), {
            "sample": self.sample.pk, "nil": "0.10", "tb1": "0.20", "tb2": "0.15", "mitogen": "5",
            "test_date": "2026-11-04", "performed_by": self.admin.pk})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Quantiferon.objects.get(run__isnull=True).interpretation, "NEG")
        r = self.client.post(reverse("diagnostic:quantiferon_create"), {
            "sample": self.sample.pk, "od_nil": "0.03", "test_date": "2026-11-04"})
        self.assertContains(r, "Choisissez la plaque ELISA")


class ResultViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("adm", "a@example.org", "x")

    def test_result_preview_template(self):
        self.client.force_login(self.admin)
        p = Patient.objects.create(last_name="Ratsimanana", first_name="Jean Michel", code="PAT-014582")
        s = Sample.objects.create(code="26-5675", patient=p)
        m = Microscopy.objects.create(sample=s, grade="NEG", method="FM")
        m.result_status, m.validated_at = "VALIDATED", m.created_at      # validé sans validateur (reprise)
        m.save()
        html = self.client.get(m.get_absolute_url()).content.decode()
        for text in ("Informations générales", "Informations du patient", "Validation biologique", "Métadonnées",
                     "Historique / Traçabilité", "PAT-014582", "Non renseigné", "Fluorescence (Auramine / LED)",
                     "result-chip-neg"):
            self.assertIn(text, html)
        self.assertNotIn("par None", html)

    def test_access_list_has_no_monitoring_link(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("quality:access_list")).content.decode()
        self.assertNotIn(reverse("quality:monitoring") + '"', html.split('class="myc-content"')[1])
