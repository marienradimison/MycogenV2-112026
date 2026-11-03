from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Room, Sample
from apps.quality.models import Equipment

from .models import Culture, IncubatorReading, TemperatureLog


class CultureLJTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("bio", "b@example.org", "x")
        self.client.force_login(self.user)
        self.etuve = Equipment.objects.create(room=Room.objects.get(zone="7"), name="Étuve 37 °C n°1", category="INCUB")
        self.today = timezone.localdate()

    def culture(self, days_ago, **kw):
        s = Sample.objects.create(requested_analyses=["Cult-LJ"])
        return Culture.objects.create(sample=s, medium="LJ", inoculated_on=self.today - timedelta(days=days_ago),
                                      incubator=self.etuve, **kw)

    def read(self, data):
        payload = {"date": self.today.isoformat(), "incubator": self.etuve.pk, **data}
        r = self.client.post(reverse("diagnostic:lj_reading_new"), payload)
        self.assertEqual(r.status_code, 302)
        return IncubatorReading.objects.first()

    def test_two_tubes_created(self):
        c = self.culture(1)
        self.assertEqual([t.number for t in c.tubes.all()], [1, 2])
        self.assertEqual(c.stage[0], "INCUB")

    def test_inoculation_batch(self):
        s1 = Sample.objects.create(requested_analyses=["Cult-LJ", "GNX-RIF"])
        Sample.objects.create(requested_analyses=["GNX-RIF"])  # pas de LJ demandée
        page = self.client.get(reverse("diagnostic:lj_inoculation")).content.decode()
        self.assertIn(s1.code, page)
        self.client.post(reverse("diagnostic:lj_inoculation"), {
            "inoculated_on": self.today.isoformat(), "incubator": self.etuve.pk, "decontamination": "PETROFF",
            "samples": [s1.pk]})
        c = Culture.objects.get(sample=s1)
        self.assertEqual((c.medium, c.tubes.count(), c.incubator), ("LJ", 2, self.etuve))
        self.assertEqual(c.test_date, c.inoculated_on)   # date d'ensemencement = mise en étuve
        c.tube_count = 1
        c.save()
        self.assertEqual(c.tubes.count(), 1)
        self.assertNotIn(s1.code, self.client.get(reverse("diagnostic:lj_inoculation")).content.decode())

    def test_reading_rules(self):
        neg = self.culture(95)                 # > 90 j sans pousse → négative
        keep = self.culture(95)                # > 90 j mais sortie non confirmée → reste
        pos = self.culture(30)                 # pousse + SD positif → CMTB
        ntm = self.culture(28)                 # pousse + SD négatif → LPA
        wait = self.culture(25)                # pousse sans SD → test SD à faire
        cont2 = self.culture(10)               # 2 tubes contaminés → à retraiter
        cont1 = self.culture(12)               # 1 tube contaminé → l'autre reste
        reading = self.read({
            f"neg_{neg.pk}": "on",
            f"t1_{pos.pk}": "GROWTH", f"sd_{pos.pk}": "POS",
            f"t2_{ntm.pk}": "GROWTH", f"sd_{ntm.pk}": "NEG",
            f"t1_{wait.pk}": "GROWTH",
            f"t1_{cont2.pk}": "CONTAMINATED", f"t2_{cont2.pk}": "CONTAMINATED",
            f"t1_{cont1.pk}": "CONTAMINATED", f"t2_{cont1.pk}": "NOGROWTH",
        })
        for c in (neg, keep, pos, ntm, wait, cont2, cont1):
            c.refresh_from_db()
        self.assertEqual((neg.result, neg.result_date), ("NEGATIVE", self.today))
        self.assertEqual(keep.result, "PENDING")
        self.assertEqual((pos.result, pos.identification, pos.ttp_days), ("POSITIVE", "MTBC", 30))
        self.assertEqual((ntm.result, ntm.identification, ntm.stage[0]), ("POSITIVE", "NON_MTBC", "LPA"))
        self.assertEqual((wait.result, wait.stage[0]), ("PENDING", "SD"))
        self.assertEqual((cont2.result, cont2.retreat_status), ("CONTAMINATED", "TO_RETREAT"))
        self.assertEqual(cont1.result, "PENDING")
        self.assertEqual([t.status for t in cont1.tubes.all()], ["CONTAMINATED", "INCUB"])
        self.assertTrue(all(t.status == "EXITED" for t in pos.tubes.all()))
        actions = dict(reading.entries.values_list("culture_id", "action"))
        self.assertEqual(actions[cont1.pk], "TUBE_DISCARDED")
        self.assertEqual(actions[wait.pk], "GROWTH_SD")
        # lecture suivante : SD positif sur la pousse en attente
        self.read({f"sd_{wait.pk}": "POS"})
        wait.refresh_from_db()
        self.assertEqual((wait.result, wait.identification), ("POSITIVE", "MTBC"))
        # fiche de lecture (écran + document imprimable)
        html = self.client.get(reading.get_absolute_url()).content.decode()
        for c in (neg, pos, ntm, cont2, cont1):
            self.assertIn(c.sample.code, html)
        doc = self.client.get(reading.get_absolute_url() + "?print=1").content.decode()
        self.assertIn("FICHE DE LECTURE", doc)
        self.assertEqual(doc.count("<tr class=\"dec-"), 7)   # une seule fiche, une ligne par culture lue
        blank = self.client.get(reverse("diagnostic:lj_blank_sheet")).content.decode()
        self.assertIn("Fiche vierge", blank)
        self.assertIn(keep.sample.code, blank)
        # retraitement
        self.client.post(reverse("diagnostic:lj_inoculation"), {
            "inoculated_on": self.today.isoformat(), "decontamination": "PETROFF", "retreat": [cont2.pk]})
        cont2.refresh_from_db()
        self.assertEqual(cont2.retreat_status, "RETREATED")
        self.assertEqual(Culture.objects.get(retreat_of=cont2).result, "PENDING")
        self.assertEqual(cont2.retreated_on, self.today)   # date de retraitement = 2e ensemencement

    def test_pages_and_temperature(self):
        self.culture(40)
        for name in ("lj_home", "lj_inoculation", "lj_reading_new", "lj_readings", "lj_temperatures"):
            self.assertEqual(self.client.get(reverse(f"diagnostic:{name}")).status_code, 200, name)
        url = reverse("diagnostic:lj_temperatures")
        r = self.client.post(url, {"incubator": self.etuve.pk, "measured_at": "2026-10-14T08:00", "value": "39.5"})
        self.assertContains(r, "action corrective")       # hors plage sans commentaire → refus
        self.client.post(url, {"incubator": self.etuve.pk, "measured_at": "2026-10-14T08:00", "value": "39.5",
                               "comment": "Porte mal fermée, réglage vérifié"})
        self.assertTrue(TemperatureLog.objects.get().out_of_range)
        self.assertContains(self.client.get(reverse("quality:monitoring")), "39.5")
