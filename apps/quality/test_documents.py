import base64
import shutil
import tempfile

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import UserProfile

from .models import QualityDocument

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
MEDIA = tempfile.mkdtemp(prefix="mycogen-test-media-")


@override_settings(MEDIA_ROOT=MEDIA)
class SignatureAndDocumentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_mycogen", verbosity=0)
        cls.mb = User.objects.create_user("bio", password="x", first_name="Hanta", last_name="Rakoto")
        cls.mb.groups.add(Group.objects.get(role_code__code="MB"))
        profile, _ = UserProfile.objects.get_or_create(user=cls.mb)
        profile.job_title = "Médecin biologiste"
        profile.signature = SimpleUploadedFile("sig.png", PNG, content_type="image/png")
        profile.save()
        cls.cds = User.objects.create_user("chef", password="x", first_name="Voahangy", last_name="R")
        cls.cds.groups.add(Group.objects.get(role_code__code="CDS"))
        UserProfile.objects.update_or_create(user=cls.cds, defaults={"signature": profile.signature.name})
        cls.tl = User.objects.create_user("tech", password="x")
        cls.tl.groups.add(Group.objects.get(role_code__code="TL"))

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def test_signature_on_validated_report(self):
        from apps.core.models import Sample
        from apps.diagnostic.models import Microscopy

        s = Sample.objects.create()
        m = Microscopy.objects.create(sample=s, grade="NEG")
        self.client.force_login(self.mb)
        html = self.client.get(reverse("core:sample_report", args=[s.pk])).content.decode()
        self.assertNotIn("data:image/png;base64", html)             # pas encore validé
        m.validate(self.mb)
        html = self.client.get(reverse("core:sample_report", args=[s.pk])).content.decode()
        self.assertIn("data:image/png;base64", html)
        self.assertIn("Hanta Rakoto, Médecin biologiste", html)
        self.assertContains(self.client.get(reverse("core:validation")), "Signature apposée")

    def test_document_approval_signed_and_versioning(self):
        self.client.force_login(self.cds)
        r = self.client.post(reverse("quality:document_create"), {
            "reference": "MYC-SOP-001", "title": "Coloration auramine", "category": "SOP", "version": "01",
            "status": "DRAFT", "author": self.cds.pk, "file": SimpleUploadedFile("sop.pdf", b"%PDF-1.4 test", content_type="application/pdf")})
        self.assertEqual(r.status_code, 302)
        v1 = QualityDocument.objects.get(reference="MYC-SOP-001")
        self.assertEqual(v1.author, self.cds)
        self.client.post(reverse("quality:document_approve", args=[v1.pk]), {"comment": "OK"})
        v1.refresh_from_db()
        self.assertEqual((v1.status, v1.approved_by), ("APPROVED", self.cds))
        self.assertIsNotNone(v1.effective_on)
        self.assertContains(self.client.get(v1.get_absolute_url()), "data:image/png;base64")
        # nouvelle version approuvée : l'ancienne est archivée
        v2 = QualityDocument.objects.create(reference="MYC-SOP-001", title="Coloration auramine", version="02",
                                            file=SimpleUploadedFile("sop2.pdf", b"%PDF-1.4"))
        v2.approve(self.cds)
        v1.refresh_from_db()
        self.assertEqual(v1.status, "ARCHIVED")
        # un document approuvé dont le fichier change repart en brouillon
        v2.file = SimpleUploadedFile("sop2b.pdf", b"%PDF-1.4 b")
        v2.save()
        self.assertEqual((v2.status, v2.approved_by), ("DRAFT", None))
        # « en vigueur » impossible sans approbation
        d = QualityDocument.objects.create(reference="MYC-COMM-001", title="Note", category="COMM", status="APPROVED")
        self.assertEqual(d.status, "REVIEW")

    def test_document_access_reserved_to_sgq_roles(self):
        doc = QualityDocument.objects.create(reference="MYC-MQ-001", title="Manuel qualité", category="MQ",
                                             file=SimpleUploadedFile("mq.pdf", b"%PDF"))
        self.client.force_login(self.tl)
        self.assertEqual(self.client.get(reverse("quality:document_list")).status_code, 200)   # lecture : tous
        self.assertEqual(self.client.post(reverse("quality:document_approve", args=[doc.pk])).status_code, 403)
        doc.refresh_from_db()
        self.assertEqual(doc.status, "DRAFT")

    def test_sgq_menu(self):
        from apps.core.menu import build_menu

        mb_sgq = next(m for m in build_menu(self.mb)[0] if m["key"] == "quality")   # MB : documents seulement
        self.assertEqual([i["label"] for i in mb_sgq["items"]], ["DQ — Documents qualité"])
        sidebar, _ = build_menu(self.cds)
        sgq = next(m for m in sidebar if m["key"] == "quality")
        self.assertEqual(sgq["label"], "SGQ")
        self.assertEqual([i["label"] for i in sgq["items"]],
                         ["Suivi performance", "Matériels", "Accès aux salles", "DQ — Documents qualité"])
        research = next(m for m in sidebar if m["key"] == "research")
        labels = [i["label"] for i in research["items"]]
        self.assertIn("Cahiers de laboratoire", labels)
        self.assertIn("MycoLearn", labels)
        self.assertNotIn("Pipelines", labels)
        self.assertNotIn("Analyses génomiques", labels)
