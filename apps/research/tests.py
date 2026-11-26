import shutil
import tempfile

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import LabNotebook, LearningDomain, LearningResource, NotebookEntry

MEDIA = tempfile.mkdtemp(prefix="mycogen-test-media-")


@override_settings(MEDIA_ROOT=MEDIA)
class NotebookAndMycoLearnTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_mycogen", verbosity=0)
        cls.rsr = User.objects.create_user("chercheur", password="x")
        cls.rsr.groups.add(Group.objects.get(role_code__code="RSR"))
        cls.al = User.objects.create_user("agent", password="x")
        cls.al.groups.add(Group.objects.get(role_code__code="AL"))

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def test_notebook_with_entries(self):
        self.client.force_login(self.rsr)
        form = self.client.get(reverse("research:notebook_create")).context["form"]
        self.assertEqual(form.initial["owner"], self.rsr.pk)                 # titulaire pré-rempli
        r = self.client.post(reverse("research:notebook_create"), {
            "code": "CL-2026-001", "title": "Extraction ADN", "kind": "ELEC", "status": "OPEN",
            "started_on": "2026-11-01", "owner": self.rsr.pk})
        self.assertEqual(r.status_code, 302)
        nb = LabNotebook.objects.get(code="CL-2026-001")
        self.assertEqual(nb.owner, self.rsr)
        NotebookEntry.objects.create(notebook=nb, title="Essai kit Qiagen", content="Rendement 45 ng/µL")
        self.assertContains(self.client.get(nb.get_absolute_url()), "Essai kit Qiagen")
        # recherche dans le contenu des entrées
        self.assertContains(self.client.get(reverse("research:notebook_list"), {"q": "Qiagen"}), "CL-2026-001")

    def test_mycolearn_gallery(self):
        domain = LearningDomain.objects.get(name="Bioinformatique")          # domaines créés par la migration
        LearningResource.objects.create(title="Introduction à TB-Profiler", domain=domain, kind="VIDEO",
                                        file=SimpleUploadedFile("intro.mp4", b"\x00\x00"))
        LearningResource.objects.create(title="Brouillon caché", domain=domain, kind="LINK",
                                        url="https://example.org", published=False)
        self.client.force_login(self.al)                                    # MycoLearn : consultation
        page = self.client.get(reverse("research:mycolearn"), {"domaine": domain.pk})
        self.assertContains(page, "Introduction à TB-Profiler")
        self.assertNotContains(page, "Brouillon caché")
        self.assertNotContains(page, "Ajouter un support")
        self.assertEqual(self.client.get(reverse("research:learning_create")).status_code, 403)
        res = LearningResource.objects.get(title="Introduction à TB-Profiler")
        self.assertContains(self.client.get(res.get_absolute_url()), "<video")
        nobody = User.objects.create_user("sansrole", password="x")                # compte sans rôle
        self.client.force_login(nobody)
        self.assertEqual(self.client.get(reverse("research:mycolearn")).status_code, 403)
        self.client.force_login(self.rsr)
        self.assertContains(self.client.get(reverse("research:mycolearn")), "Brouillon caché")
        # ni fichier ni lien : refusé
        r = self.client.post(reverse("research:learning_create"), {"title": "Vide", "domain": domain.pk,
                                                                   "kind": "PDF", "level": "BEG", "published": "on"})
        self.assertContains(r, "Joignez un fichier ou indiquez un lien")
