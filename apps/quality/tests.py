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

    def test_technician_read_only(self):
        self.tech.groups.add(Group.objects.get(role_code__code="TL"))
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(reverse("quality:equipment_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("quality:equipment_create")).status_code, 403)
