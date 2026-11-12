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
        self.assertIn("FICHE PAILLASSE SORTIE CULTURES", doc)
        self.assertIn("MYC-FIC-008/02", doc)
        self.assertEqual(doc.count('class="fiche-lj"'), 1)      # une seule fiche par lecture
        self.assertEqual(doc.count('<td class="lab">' + pos.sample.code[:3]), 7)   # une ligne par culture lue
        self.assertIn(keep.sample.code, doc)
        blank = self.client.get(reverse("diagnostic:lj_blank_sheet")).content.decode()
        self.assertIn("FICHE PAILLASSE SORTIE CULTURES", blank)
        self.assertIn(keep.sample.code, blank)
        # retraitement
        self.client.post(reverse("diagnostic:lj_inoculation"), {
            "inoculated_on": self.today.isoformat(), "decontamination": "PETROFF", "retreat": [cont2.pk]})
        cont2.refresh_from_db()
        self.assertEqual(cont2.retreat_status, "RETREATED")
        self.assertEqual(Culture.objects.get(retreat_of=cont2).result, "PENDING")
        self.assertEqual(cont2.retreated_on, self.today)   # date de retraitement = 2e ensemencement

    def test_reading_age_filters_and_group_negative(self):
        monday = self.today - timedelta(days=self.today.weekday())
        old = Culture.objects.create(sample=Sample.objects.create(), medium="LJ", inoculated_on=monday - timedelta(days=100))
        soon = Culture.objects.create(sample=Sample.objects.create(), medium="LJ", inoculated_on=monday - timedelta(days=88))
        young = Culture.objects.create(sample=Sample.objects.create(), medium="LJ", inoculated_on=monday - timedelta(days=10))
        url = reverse("diagnostic:lj_reading_new")
        day = monday.isoformat()
        shown = lambda q: [c.pk for c in self.client.get(url + q).context["cultures"]]
        self.assertEqual(shown(f"?date={day}"), [old.pk, soon.pk, young.pk])
        self.assertEqual(shown(f"?filtre=90&date={day}"), [old.pk])
        self.assertEqual(shown(f"?filtre=90s&date={day}"), [old.pk, soon.pk])
        self.assertTrue(all(c.suggest_negative for c in self.client.get(url + f"?filtre=90s&date={day}").context["cultures"]))
        # sans l'option « fin de semaine », une culture de moins de 90 j ne peut pas sortir négative
        self.client.post(url, {"date": day, "cultures": [soon.pk], f"neg_{soon.pk}": "on"})
        soon.refresh_from_db()
        self.assertEqual(soon.result, "PENDING")
        # sortie en groupe : seules les cultures affichées font partie de la lecture
        r = self.client.post(url, {"date": day, "filtre": "90s", "cultures": [old.pk, soon.pk],
                                   f"neg_{old.pk}": "on", f"neg_{soon.pk}": "on"})
        self.assertEqual(r.status_code, 302)
        for c in (old, soon, young):
            c.refresh_from_db()
        self.assertEqual((old.result, soon.result, young.result), ("NEGATIVE", "NEGATIVE", "PENDING"))
        reading = IncubatorReading.objects.first()
        self.assertEqual(reading.entries.count(), 2)
        self.assertFalse(reading.entries.filter(culture=young).exists())

    def test_reading_sheet_fields(self):
        pos = self.culture(30)
        exact = self.culture(28)
        neg = self.culture(95)
        invalid = self.culture(26)
        reading = self.read({
            f"t1_{pos.pk}": "GROWTH", f"sd_{pos.pk}": "POS", f"sdc_{pos.pk}": "+", f"colonies_{pos.pk}": "200",
            f"morph_{pos.pk}": ["R", "E"], f"pigment_{pos.pk}": "Beige", f"baar_{pos.pk}": "id BK",
            f"conclusion_{pos.pk}": "CMTB", f"cjlj_{pos.pk}": "on",
            f"t1_{exact.pk}": "GROWTH", f"colonies_{exact.pk}": "15",
            f"neg_{neg.pk}": "on",
            f"t1_{invalid.pk}": "GROWTH", f"sd_{invalid.pk}": "POS", f"sdc_{invalid.pk}": "-",
        })
        for c in (pos, exact, neg, invalid):
            c.refresh_from_db()
        e = reading.entries.get(culture=pos)
        self.assertEqual((e.colonies, e.morphology, e.pigment, e.baar_aspect, e.sd_control, e.conclusion, e.cj_lj, e.cj_pyr),
                         ("200", "ER", "Beige", "id BK", "+", "CMTB", True, False))
        self.assertEqual(e.growth_days, 30)
        self.assertEqual((pos.result, pos.lj_grade, pos.colony_count), ("POSITIVE", "2+", None))
        self.assertEqual((exact.lj_grade, exact.colony_count), ("1-19", 15))
        self.assertEqual(reading.entries.get(culture=neg).colonies, "0")
        self.assertEqual(invalid.result, "PENDING")             # contrôle négatif : test à refaire
        self.assertEqual(reading.entries.get(culture=invalid).action, "GROWTH_SD")
        doc = self.client.get(reading.get_absolute_url() + "?print=1").content.decode()
        for text in ("<td>200</td>", "<td>ER</td>", ">Beige<", ">id BK<", "<td>30 j</td>", ">CMTB<", "<td>X</td>"):
            self.assertIn(text, doc)
        self.assertIn("Beige", self.client.get(reading.get_absolute_url()).content.decode())
        # lecture suivante d'une pousse : la fiche déjà saisie est reprise
        ctx = self.client.get(reverse("diagnostic:lj_reading_new")).context["cultures"]
        self.assertEqual(next(c for c in ctx if c.pk == exact.pk).prev.colonies, "15")

    def test_sheet_pages_of_24_rows(self):
        for i in range(30):
            Culture.objects.create(sample=Sample.objects.create(), medium="LJ", inoculated_on=self.today - timedelta(days=5))
        doc = self.client.get(reverse("diagnostic:lj_blank_sheet")).content.decode()
        self.assertEqual(doc.count('class="fiche-lj"'), 2)
        self.assertEqual(doc.count('<td class="lab">'), 48)      # 2 pages de 24 lignes, complétées à vide
        self.assertIn("Page 2 / 2", doc)

    def test_retreatment_page(self):
        first = self.culture(40, result="CONTAMINATED", result_date=self.today, retreat_status="RETREATED")
        second = Culture.objects.create(sample=first.sample, medium="LJ", retreat_of=first, inoculated_on=self.today - timedelta(days=20),
                                        result="CONTAMINATED", result_date=self.today, retreat_status="RETREATED")
        third = Culture.objects.create(sample=first.sample, medium="LJ", retreat_of=second, inoculated_on=self.today - timedelta(days=2))
        todo = self.culture(30, result="CONTAMINATED", result_date=self.today, retreat_status="TO_RETREAT")
        r = self.client.get(reverse("diagnostic:lj_retreatment"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c.pk for c in r.context["to_retreat"]], [todo.pk])
        row = r.context["history"][0]
        self.assertEqual((row["sample"], row["count"], row["latest"]), (first.sample, 2, third))
        self.assertContains(r, "Tous les retraitements")
        self.assertContains(self.client.get(reverse("diagnostic:lj_home")), reverse("diagnostic:lj_retreatment"))

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
