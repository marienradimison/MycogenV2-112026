from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import ActivityLog, Patient, Sample
from apps.research.models import Project

from .models import BiobankItem, BoxMovement, InventoryLine, InventorySession, Movement, StorageBox, StorageUnit

YEAR = timezone.localdate().year


class BoxNamingTests(TestCase):
    def setUp(self):
        self.unit = StorageUnit.objects.create(name="MYCO-2209", type="-80")

    def test_auto_numbering_per_type_and_year(self):
        a = StorageBox.objects.create(unit=self.unit, item_type="ISOLATE")
        b = StorageBox.objects.create(unit=self.unit, item_type="ISOLATE")
        c = StorageBox.objects.create(unit=self.unit, item_type="DNA")
        old = StorageBox.objects.create(unit=self.unit, item_type="ISOLATE", year=YEAR - 1)
        self.assertEqual([a.name, b.name, c.name, old.name],
                         [f"SCH-{YEAR}-01", f"SCH-{YEAR}-02", f"ADN-{YEAR}-01", f"SCH-{YEAR - 1}-01"])

    def test_manual_number_and_name(self):
        m = StorageBox.objects.create(unit=self.unit, item_type="PLASMA", number=4)
        self.assertEqual(m.name, f"PLA-{YEAR}-04")
        self.assertEqual(StorageBox.objects.create(unit=self.unit, item_type="PLASMA").name, f"PLA-{YEAR}-05")
        n = StorageBox.objects.create(unit=self.unit, name="adn-2027-12")  # type, année et n° déduits du nom
        self.assertEqual((n.name, n.item_type, n.year, n.number), ("ADN-2027-12", "DNA", 2027, 12))

    def test_path_and_levels(self):
        box = StorageBox.objects.create(unit=self.unit, item_type="ISOLATE", shelf="3", rack="1")
        self.assertEqual(box.path, f"MYCO-2209/E03/R01/SCH-{YEAR}-01")
        self.assertEqual(box.format_display, "9x9 : 81 positions")
        self.assertEqual(box.label, "SOUCHES")


class ItemTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tl")
        self.unit = StorageUnit.objects.create(name="MYCO-2209", type="-80")
        self.box = StorageBox.objects.create(unit=self.unit, item_type="ISOLATE", shelf="E03", rack="R01")
        self.project = Project.objects.create(code="TB-GEN", title="t", principal_investigator="pi")
        self.sample = Sample.objects.create(project=self.project, patient=Patient.objects.create(code="EXT-77"))

    def test_code_project_label_from_sample(self):
        a = BiobankItem.objects.create(item_type="ISOLATE", sample=self.sample, box=self.box, position="b07")
        b = BiobankItem.objects.create(item_type="DNA", parent=a)
        c = BiobankItem.objects.create(item_type="DNA", sample=self.sample)
        self.assertEqual([a.code, b.code, c.code], [self.sample.code, f"{self.sample.code}-2", f"{self.sample.code}-3"])
        self.assertEqual((a.project, a.label, b.sample, b.project), (self.project, "EXT-77", self.sample, self.project))
        self.assertEqual(a.path, f"MYCO-2209/E03/R01/SCH-{YEAR}-01/B07")
        self.assertEqual(a.position, "B7")

    def test_entries_and_moves_are_traced(self):
        item = BiobankItem.objects.create(item_type="ISOLATE", sample=self.sample, box=self.box, position="A1",
                                          created_by=self.user)
        entry = item.movements.get()
        self.assertEqual((entry.type, entry.to_location, entry.operator), ("IN", item.path, self.user))
        item.position = "C3"
        item.save()
        move = item.movements.get(type="MOVE")
        self.assertTrue(move.from_location.endswith("/A01") and move.to_location.endswith("/C03"))

    def test_move_movement(self):
        item = BiobankItem.objects.create(item_type="ISOLATE", sample=self.sample, box=self.box, position="A1")
        other = BiobankItem.objects.create(item_type="ISOLATE", sample=self.sample, box=self.box, position="A2")
        box2 = StorageBox.objects.create(unit=self.unit, item_type="ISOLATE")
        bad = Movement(item=item, type="MOVE", to_box=self.box, to_position="A2")
        with self.assertRaises(Exception):
            bad.full_clean()
        Movement.objects.create(item=item, type="MOVE", to_box=box2, to_position="D4")
        item.refresh_from_db()
        self.assertEqual((item.box, item.position), (box2, "D4"))
        self.assertEqual(item.movements.filter(type="MOVE").count(), 1)  # pas de double trace
        Movement.objects.create(item=other, type="THAW")
        other.refresh_from_db()
        self.assertEqual(other.freeze_thaw, 1)


class InventoryTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin-bb", "a@example.org", "x")
        self.client.force_login(self.admin)
        self.unit = StorageUnit.objects.create(name="MYCO-2209", type="-80")
        self.box = StorageBox.objects.create(unit=self.unit, item_type="ISOLATE", shelf="1", rack="1")
        s = Sample.objects.create()
        self.a = BiobankItem.objects.create(item_type="ISOLATE", sample=s, box=self.box, position="A1")
        self.b = BiobankItem.objects.create(item_type="ISOLATE", sample=s, box=self.box, position="A2")
        self.session = InventorySession.objects.create(unit=self.unit, shelf="E01", performed_by=self.admin)
        self.session.populate()

    def test_workflow(self):
        s = self.session
        self.assertEqual(s.lines.count(), 3)  # la boîte + 2 aliquots
        scan = reverse("biobank:inventory_scan", args=[s.pk])
        self.client.post(scan, {"code": self.a.code, "box": self.box.pk, "position": "A1"})
        self.client.post(scan, {"code": self.b.code, "box": self.box.pk, "position": "B05"})
        self.client.post(scan, {"code": "INCONNU-1", "box": self.box.pk, "position": "C1"})
        statuses = {l.expected_item.code if l.expected_item else l.found_code: l.status
                    for l in s.lines.filter(kind="ITEM")}
        self.assertEqual(statuses, {self.a.code: "OK", self.b.code: "MISPLACED", "INCONNU-1": "UNREGISTERED"})
        self.client.post(reverse("biobank:inventory_submit", args=[s.pk]))
        s.refresh_from_db()
        self.assertEqual(s.status, "OPEN")  # la boîte reste à vérifier
        box_line = s.lines.get(kind="BOX")
        self.client.post(reverse("biobank:inventory_save", args=[s.pk]), {f"status_{box_line.pk}": "OK"})
        self.client.post(reverse("biobank:inventory_submit", args=[s.pk]))
        self.client.post(reverse("biobank:inventory_validate", args=[s.pk]), {"apply": "1", "comment": "RAS"})
        s.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual((s.status, s.validated_by), ("VALIDATED", self.admin))
        self.assertEqual(self.b.position, "B5")  # position corrigée, tracée
        self.assertTrue(self.b.movements.filter(type="MOVE", reason__contains=s.code).exists())

    def test_validation_requires_permission(self):
        tl = User.objects.create_user("tl-bb")
        self.client.force_login(tl)
        self.assertEqual(self.client.post(reverse("biobank:inventory_validate", args=[self.session.pk])).status_code, 403)


class PageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin-bb", "a@example.org", "x")
        self.client.force_login(self.admin)
        self.unit = StorageUnit.objects.create(name="MYCO-2209", type="-80")
        self.box = StorageBox.objects.create(unit=self.unit, item_type="ISOLATE", shelf="1", rack="1")
        self.sample = Sample.objects.create(host="Bovin", patient=Patient.objects.create(code="EXT-1"))
        self.item = BiobankItem.objects.create(item_type="ISOLATE", sample=self.sample, box=self.box, position="A1")
        BiobankItem.objects.create(item_type="DNA", parent=self.item)
        inv = InventorySession.objects.create(unit=self.unit)
        inv.populate()

    def test_pages(self):
        trace, rep = reverse("biobank:trace"), reverse("biobank:reports")
        urls = [reverse("biobank:box_label", args=[self.box.pk]), f"{reverse('biobank:box_labels')}?ids={self.box.pk}",
                trace, f"{trace}?q={self.item.code}", f"{trace}?q={self.box.name}", f"{trace}?q={self.sample.code}",
                f"{trace}?q=zz", f"{trace}?onglet=journal&type=IN&du=2020-01-01", f"{trace}?onglet=audit",
                reverse("biobank:inventory_detail", args=[InventorySession.objects.get().pk]),
                reverse("biobank:box_detail", args=[self.box.pk]), reverse("biobank:item_detail", args=[self.item.pk]),
                reverse("biobank:anomaly_list"), reverse("core:module", args=["biobank"])]
        for tab in ("effectifs", "occupation", "capacites", "flux", "inventaires"):
            urls += [f"{rep}?onglet={tab}", f"{rep}?onglet={tab}&annee={YEAR}&espece=Bovin&export=csv",
                     f"{rep}?onglet={tab}&export=xlsx"]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        page = self.client.get(reverse("biobank:item_list")).content.decode()
        self.assertIn("Aliquots &amp; Souches", page)

    def test_source_info(self):
        r = self.client.get(reverse("biobank:source_info"), {"parent": self.item.pk}).json()
        self.assertEqual((r["sample"], r["label"]), (self.sample.pk, "EXT-1"))

    def test_box_move(self):
        unit2 = StorageUnit.objects.create(name="MYCO-2210", type="-80")
        self.client.post(reverse("biobank:box_move", args=[self.box.pk]),
                         {"unit": unit2.pk, "shelf": "2", "rack": "4", "reason": "dégivrage"})
        self.box.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.box.path, f"MYCO-2210/E02/R04/SCH-{YEAR}-01")
        self.assertTrue(self.item.path.startswith("MYCO-2210/E02/R04/"))
        self.assertEqual(BoxMovement.objects.get().from_location, f"MYCO-2209/E01/R01/SCH-{YEAR}-01")
        self.assertTrue(ActivityLog.objects.filter(action="UPDATE", object_id=str(self.box.pk)).exists())

    def test_create_box_form_autonames(self):
        self.client.post(reverse("biobank:box_create"), {"item_type": "DNA", "unit": self.unit.pk, "shelf": "3",
                                                         "rack": "", "rows": 9, "cols": 9})
        self.assertTrue(StorageBox.objects.filter(name=f"ADN-{YEAR}-01", shelf="E03").exists())
        self.assertEqual(InventoryLine.objects.count(), 2)
