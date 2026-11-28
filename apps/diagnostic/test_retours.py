"""Retours terrain du 28/11/2026."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Patient, Sample

from .models import Culture, CultureTube, GeneXpertTest


class FieldFeedbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("adm", "a@example.org", "x")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_external_id_left_empty_and_tb_history_unknown(self):
        p = Patient.objects.create(last_name="RAKOTO", sex="M")
        self.assertEqual(p.code, "")
        self.assertEqual(str(p), "RAKOTO")
        self.assertEqual(p.tb_history, "UNK")
        form = self.client.get(reverse("core:register")).content.decode()
        self.assertNotIn("Consentement pour la recherche", form)
        self.assertIn('value="UNK" selected', form)
        # identifiants automatiques existants : simulation puis effacement
        auto = Patient.objects.create(last_name="ANCIEN", sex="F", code="PT26-00042")
        call_command("clear_auto_patient_codes", stdout=open("NUL" if __import__("os").name == "nt" else "/dev/null", "w"))
        auto.refresh_from_db()
        self.assertEqual(auto.code, "PT26-00042")
        call_command("clear_auto_patient_codes", "--apply", stdout=open("NUL" if __import__("os").name == "nt" else "/dev/null", "w"))
        auto.refresh_from_db()
        self.assertEqual(auto.code, "")

    def test_gnx_rif_shows_only_rifampicin(self):
        s = Sample.objects.create()
        r = self.client.post(reverse("diagnostic:genexpert_create"), {
            "sample": s.pk, "assay": "ULTRA", "mtb_result": "LOW", "rif_result": "NOT_DETECTED",
            "inh_result": "DETECTED", "fq_result": "DETECTED", "test_date": "2026-11-28"})
        self.assertEqual(r.status_code, 302)
        gx = GeneXpertTest.objects.get(sample=s)
        self.assertEqual((gx.inh_result, gx.fq_result), ("NA", "NA"))           # pas d'autre antibiotique
        page = self.client.get(gx.get_absolute_url()).content.decode()
        self.assertIn("Résistance RIF", page)
        self.assertNotIn("Résistance INH", page)
        self.assertIn("field-inh_result", self.client.get(reverse("diagnostic:genexpert_create")).content.decode())

    def test_validation_lists_only_results_entered(self):
        s = Sample.objects.create()
        pending = Culture.objects.create(sample=s, medium="LJ", inoculated_on=timezone.localdate())
        done = Culture.objects.create(sample=s, medium="MGIT", inoculated_on=timezone.localdate(), result="NEGATIVE")
        page = self.client.get(reverse("core:validation"), {"statut": "tous"}).content.decode()
        self.assertNotIn(f'value="culture:{pending.pk}"', page)
        self.assertIn(f'value="culture:{done.pk}"', page)
        self.client.post(reverse("core:validation"), {"items": [f"culture:{pending.pk}"]})
        pending.refresh_from_db()
        self.assertEqual(pending.result_status, "DRAFT")                       # non validable sans résultat
        self.assertNotContains(self.client.get(pending.get_absolute_url()), 'data-bs-target="#validateModal"')

    def test_lj_inoculation_defaults_to_nalc(self):
        self.assertIn('<option value="NALC" selected>', self.client.get(reverse("diagnostic:lj_inoculation")).content.decode())


class IncubatorReadingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("adm", "a@example.org", "x")
        today = timezone.localdate()
        cls.cultures = []
        for i in range(300):   # grande étuve : plus de 1 000 champs de formulaire
            p = Patient.objects.create(last_name=f"PATIENT{i}", sex="M", code=f"EXT-{i}")
            s = Sample.objects.create(code=f"26-{7000 + i}", patient=p)
            c = Culture.objects.create(sample=s, medium="LJ", tube_count=2,
                                       inoculated_on=today - timedelta(days=100 if i % 2 else 20))
            if not c.tubes.exists():
                for n in (1, 2):
                    CultureTube.objects.create(culture=c, number=n)
            cls.cultures.append(c)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_large_reading_is_saved(self):
        data = {"date": timezone.localdate().isoformat(), "filtre": "", "incubator": "", "notes": ""}
        data["cultures"] = [str(c.pk) for c in self.cultures]
        for c in self.cultures:
            for key in ("t1", "t2", "sd", "colonies", "morph", "pigment", "baar", "sdc", "conclusion"):
                data[f"{key}_{c.pk}"] = ""
            data[f"t1_{c.pk}"] = "NOGROWTH"
        r = self.client.post(reverse("diagnostic:lj_reading_new"), data)
        self.assertEqual(r.status_code, 302)                                 # avant : 400 TooManyFieldsSent

    def test_search_filters_and_labels(self):
        url = reverse("diagnostic:lj_reading_new")
        page = self.client.get(url).content.decode()
        for label in ("&gt;90 jours", "semaine | &gt;90 jours", "Ouvrir toutes les fiches", "Fermer toutes les fiches",
                      "Rechercher un échantillon", "Mois d'ensemencement"):
            self.assertIn(label, page)
        self.assertNotIn("90 jours et plus", page)
        one = self.client.get(url, {"q": "26-7005"}).content.decode()
        self.assertIn("26-7005", one)
        self.assertNotIn("26-7006", one)
        self.assertIn("1 culture(s) sur 300", one)
        self.assertIn("26-7007", self.client.get(url, {"q": "ext-7"}).content.decode())   # identifiant externe
        old = (timezone.localdate() - timedelta(days=100)).isoformat()
        by_date = self.client.get(url, {"ensemence": old}).content.decode()
        self.assertIn("150 culture(s) sur 300", by_date)
        month = (timezone.localdate() - timedelta(days=100)).strftime("%Y-%m")
        self.assertIn("150 culture(s) sur 300", self.client.get(url, {"mois": month}).content.decode())
