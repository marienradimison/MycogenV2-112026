"""Matrice des autorisations par rôle (fichier « permissions.xlsx » du 26/11/2026)."""
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

ALL_ROLES = ["AS", "SL", "TL", "MB", "CDS", "RQ/CQ", "RSR", "AL", "STG"]

# (permission, rôles autorisés) — ligne par ligne du fichier
MATRIX = [
    ("core.view_facility", ALL_ROLES),                                            # Structures : consulter
    ("research.view_learningresource", ALL_ROLES),                                # MycoLearn : consulter
    ("research.add_learningresource", ["SL", "RSR", "RQ/CQ", "CDS"]),             # MycoLearn : ajouter
    ("research.delete_learningresource", ["SL", "RSR", "RQ/CQ", "CDS"]),          # MycoLearn : supprimer
    ("quality.view_qualitydocument", ALL_ROLES),                                  # SOP : consulter
    ("quality.change_qualitydocument", ["SL", "RQ/CQ", "CDS"]),
    ("diagnostic.add_temperaturelog", ["AS", "SL", "TL", "MB", "CDS", "RQ/CQ", "AL"]),  # températures
    ("core.view_sample", ["AS", "SL", "TL", "MB", "CDS", "RQ/CQ"]),               # Échantillons
    ("core.add_sample", ["AS", "SL", "TL", "MB", "CDS", "RQ/CQ"]),                # Enregistrer
    ("core.change_sample", ["AS", "SL", "TL", "MB", "CDS", "RQ/CQ"]),             # Saisir / modifier
    ("core.delete_sample", []),                                                   # administrateur seulement
    ("core.validate_results", ["SL", "MB", "CDS"]),                               # Validation : valider
    ("core.view_validation", ["AS", "SL", "TL", "MB", "CDS", "RQ/CQ"]),           # Validation : exporter
    ("core.add_facility", ["SL", "RQ/CQ", "CDS"]),                                # Structures : ajouter
    ("diagnostic.add_genexperttest", ["AS", "SL", "TL", "MB", "CDS", "RQ/CQ"]),   # Analyses TB : toutes
    ("diagnostic.view_culture", ["AS", "SL", "TL", "MB", "CDS", "RQ/CQ", "RSR"]),  # + RSR : consulter
    ("research.add_project", ["SL", "CDS", "RQ/CQ", "RSR"]),                      # Recherche : tous
    ("research.add_labnotebook", ["SL", "CDS", "RQ/CQ", "RSR", "TL", "STG"]),     # Cahiers de laboratoire
    ("biobank.add_biobankitem", ["SL", "CDS", "RQ/CQ", "RSR", "TL", "AS"]),       # Biobanque
    ("instruments.view_instrumentmessage", ["SL", "CDS", "RQ/CQ", "RSR", "TL", "AS"]),  # Automates : suivi, messages
    ("instruments.change_instrument", ["SL", "RQ/CQ", "CDS"]),                    # Automates : configuration
    ("stock.view_article", ["SL", "RQ/CQ", "CDS"]),                               # Stock
    ("quality.view_sgq", ["SL", "RQ/CQ", "CDS"]),                                 # SGQ
    ("quality.approve_qualitydocument", ["SL", "RQ/CQ", "CDS"]),
    ("core.change_analysiscode", ["SL", "RQ/CQ", "CDS"]),                         # Bibliothèque de codes
    ("core.view_activitylog", ["SL", "RQ/CQ", "CDS"]),                            # Journal d'activité
]


class PermissionMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_mycogen", verbosity=0)
        cls.users = {}
        for code in ALL_ROLES:
            u = User.objects.create_user(f"u-{code.replace('/', '')}", password="x")
            u.groups.add(Group.objects.get(role_code__code=code))
            cls.users[code] = u

    def test_matrix(self):
        for perm, allowed in MATRIX:
            for code, user in self.users.items():
                with self.subTest(perm=perm, role=code):
                    self.assertEqual(user.has_perm(perm), code in allowed)

    def test_admin_has_full_control(self):
        admin = User.objects.create_superuser("adm", "a@example.org", "x")
        self.assertTrue(all(admin.has_perm(p) for p, _ in MATRIX))

    def test_validation_view_only_for_non_validators(self):
        url = reverse("core:validation")
        self.client.force_login(self.users["AS"])
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Valider la sélection")
        self.assertEqual(self.client.post(url, {"items": ["microscopy:1"]}).status_code, 403)
        self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 200)
        self.client.force_login(self.users["RSR"])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.users["CDS"])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_lab_agent_records_temperatures(self):
        from apps.core.menu import build_menu

        al = self.users["AL"]
        self.client.force_login(al)
        page = self.client.get(reverse("diagnostic:lj_temperatures"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Ensemencement")                     # onglets Culture LJ masqués
        self.assertEqual(self.client.get(reverse("diagnostic:lj_home")).status_code, 403)
        analyses = next(m for m in build_menu(al)[0] if m["key"] == "analyses")
        self.assertEqual([i["label"] for i in analyses["items"]], ["Températures des étuves"])
        tl_menu = next(m for m in build_menu(self.users["TL"])[0] if m["key"] == "analyses")
        self.assertNotIn("Températures des étuves", [i["label"] for i in tl_menu["items"]])   # via Culture LJ

    def test_everyone_reads_quality_documents(self):
        from apps.core.menu import build_menu

        self.client.force_login(self.users["STG"])
        self.assertEqual(self.client.get(reverse("quality:document_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("quality:document_create")).status_code, 403)
        sgq = next(m for m in build_menu(self.users["STG"])[0] if m["key"] == "quality")
        self.assertEqual([i["label"] for i in sgq["items"]], ["DQ — Documents qualité"])
