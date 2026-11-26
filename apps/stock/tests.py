from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AnalysisCode

from .models import Article, Lot, Movement


class RolesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_mycogen", verbosity=0)

    def test_roles_in_code_library(self):
        codes = dict(AnalysisCode.objects.filter(category="ROLE").values_list("code", "meaning"))
        self.assertEqual(set(codes), {"TL", "SL", "MB", "CDS", "AS", "RSR", "RQ/CQ", "AL", "STG"})
        self.assertEqual((codes["CDS"], codes["STG"]), ("Chef de Service", "Stagiaire"))
        self.assertEqual(codes["MB"], "Médecin Biologiste")
        self.assertTrue(all(c.group for c in AnalysisCode.objects.filter(category="ROLE")))
        # les rôles ne sont pas proposés comme analyses à l'enregistrement
        self.assertNotIn("TL", AnalysisCode.catalog())

    def test_permissions_are_cumulative(self):
        u = User.objects.create_user("hery", password="x")
        u.groups.add(Group.objects.get(role_code__code="STG"))
        self.assertTrue(u.has_perm("research.add_labnotebook"))
        self.assertFalse(u.has_perm("core.add_sample"))
        u = User.objects.get(pk=u.pk)   # vide le cache des permissions
        u.groups.add(Group.objects.get(role_code__code="AS"))
        self.assertTrue(u.has_perm("core.add_sample"))
        self.assertTrue(u.has_perm("research.add_labnotebook"))       # droits cumulés
        mb = Group.objects.get(role_code__code="MB")
        self.assertTrue(mb.permissions.filter(codename="validate_results").exists())
        sl = Group.objects.get(role_code__code="SL")
        self.assertTrue(sl.permissions.filter(codename="delete_article").exists())
        self.assertFalse(Group.objects.filter(name="Technicien").exists())   # anciens rôles remplacés

    def test_legacy_role_members_are_moved(self):
        old = Group.objects.create(name="Biologiste")
        u = User.objects.create_user("bio", password="x")
        u.groups.add(old)
        call_command("init_mycogen", verbosity=0)
        self.assertEqual([g.role_code.code for g in u.groups.all()], ["MB"])

    def test_user_admin_job_title(self):
        admin = User.objects.create_superuser("root", "r@example.org", "x")
        self.client.force_login(admin)
        r = self.client.get("/admin/auth/user/add/")
        self.assertContains(r, "Rôles")
        self.assertContains(r, "Poste")
        r = self.client.get(f"/admin/auth/user/{admin.pk}/change/")
        self.assertContains(r, "RQ/CQ")


class StockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_mycogen", verbosity=0)

    def setUp(self):
        self.sl = User.objects.create_user("sl", password="x")
        self.sl.groups.add(Group.objects.get(role_code__code="SL"))
        self.client.force_login(self.sl)
        self.today = timezone.localdate()
        self.art = Article.objects.create(name="Cartouche Xpert MTB/RIF Ultra", category="CARTRIDGE", unit="cartridge",
                                          min_stock=Decimal(20))

    def test_quantities_alerts_and_movements(self):
        old = Lot.objects.create(article=self.art, lot_number="A1", quantity_received=10,
                                 expiry_date=self.today + timedelta(days=30))
        Lot.objects.create(article=self.art, lot_number="A0", quantity_received=5,
                           expiry_date=self.today - timedelta(days=1))   # périmé : non compté
        self.assertEqual(self.art.quantity, 10)
        self.assertEqual(self.art.level, "low")
        r = self.client.post(reverse("stock:home"), {"lot": old.pk, "kind": "OUT", "quantity": "4",
                                                     "date": self.today.isoformat(), "destination": "Paillasse GX"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(old.remaining, 6)
        self.assertEqual(Movement.objects.get().operator, self.sl)
        r = self.client.post(reverse("stock:home"), {"lot": old.pk, "kind": "OUT", "quantity": "50",
                                                     "date": self.today.isoformat()})
        self.assertContains(r, "Stock insuffisant")
        Movement.objects.create(lot=old, kind="ADJUST", quantity=Decimal("-1"))
        self.assertEqual(old.remaining, 5)
        page = self.client.get(reverse("stock:home")).content.decode()
        self.assertIn("Cartouche Xpert", page)
        self.assertIn("Périmé", page)
        for name in ("article_list", "lot_list", "movement_list", "article_create", "lot_create"):
            self.assertEqual(self.client.get(reverse(f"stock:{name}")).status_code, 200, name)

    def test_stock_reserved_to_sl_rq_cds(self):
        al = User.objects.create_user("al", password="x")
        al.groups.add(Group.objects.get(role_code__code="AL"))
        self.client.force_login(al)
        self.assertEqual(self.client.get(reverse("stock:home")).status_code, 403)
        cds = User.objects.create_user("cds", password="x")
        cds.groups.add(Group.objects.get(role_code__code="CDS"))
        self.client.force_login(cds)
        lot = Lot.objects.create(article=self.art, lot_number="B1", quantity_received=10)
        self.assertEqual(self.client.get(reverse("stock:article_create")).status_code, 200)
        self.client.post(reverse("stock:home"), {"lot": lot.pk, "kind": "OUT", "quantity": "2",
                                                 "date": self.today.isoformat()})
        self.assertEqual(lot.remaining, 8)
