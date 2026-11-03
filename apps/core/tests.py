import tempfile
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.crud import REGISTRY
from apps.core.models import Sample
from apps.diagnostic.models import GeneXpertTest, Quantiferon
from apps.research.models import PCRAssay


class AlgorithmTests(TestCase):
    def test_quantiferon(self):
        q = Quantiferon.interpret
        self.assertEqual(q(D("0.05"), D("1.20"), D("0.30"), D("9")), "POS")
        self.assertEqual(q(D("0.05"), D("0.10"), D("0.20"), D("9")), "NEG")
        self.assertEqual(q(D("0.05"), D("0.10"), D("0.20"), D("0.3")), "IND")  # mitogène faible
        self.assertEqual(q(D("9"), D("10"), D("10"), D("10")), "IND")  # Nil > 8
        # TB − Nil ≥ 0,35 mais < 25 % du Nil → négatif
        self.assertEqual(q(D("4"), D("4.5"), D("4.5"), D("10")), "NEG")

    def test_sweeney3_score(self):
        s = Sample.objects.create()
        p = PCRAssay.objects.create(sample=s, assay="SWEENEY3", ct_gbp5=D("25"), ct_dusp3=D("27"),
                                    ct_klf2=D("24"), threshold=D("-3"))
        self.assertEqual(p.score, D("-2.000"))
        self.assertEqual(p.outcome, "POS")

    def test_sample_codes_sequential(self):
        from django.utils import timezone
        yy = f"{timezone.localdate():%y}"
        a, b = Sample.objects.create(), Sample.objects.create()
        self.assertEqual((a.code, b.code), (f"{yy}-0001", f"{yy}-0002"))
        Sample.objects.create(code=f"{yy}-9999")
        self.assertEqual(Sample.next_code(), f"{yy}-10000")  # tri numérique, pas alphabétique

    def test_split_name(self):
        from apps.core.models import Patient
        self.assertEqual(Patient.split_name("RAKOTO Jean Hery"), ("RAKOTO", "Jean Hery"))
        self.assertEqual(Patient.split_name("Jean RAKOTOSAMIMANANA"), ("RAKOTOSAMIMANANA", "Jean"))
        self.assertEqual(Patient.split_name("rabe paul"), ("RABE", "paul"))


class SmokeTests(TestCase):
    """Toutes les pages s'affichent pour un administrateur, avec données de démo."""

    @classmethod
    def setUpTestData(cls):
        call_command("init_mycogen", demo=True, verbosity=0)
        cls.admin = User.objects.create_superuser("admin-test", "a@example.org", "x")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_pages(self):
        urls = [reverse("core:dashboard"), reverse("core:search") + "?q=RA", reverse("core:activity")]
        for crud in REGISTRY.values():
            urls += [reverse(crud.url("list")), reverse(crud.url("list")) + "?export=csv"]
            urls.append(reverse(crud.url("create")))
            obj = crud.model.objects.first()
            if obj:
                urls += [reverse(crud.url("detail"), args=[obj.pk]), reverse(crud.url("update"), args=[obj.pk])]
        s = Sample.objects.first()
        urls += [reverse("core:sample_report", args=[s.pk]), reverse("core:bench_sheet", args=[s.pk]),
                 reverse("core:register"), reverse("core:validation"),
                 reverse("core:validation") + "?analyse=genexpert&du=2026-01-01&q=a"]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_validation_workflow(self):
        x = GeneXpertTest.objects.filter(result_status="DRAFT").first()
        self.client.post(reverse("diagnostic:genexpert_validate", args=[x.pk]))
        x.refresh_from_db()
        self.assertTrue(x.is_validated)
        self.assertEqual(x.validated_by, self.admin)

    def test_technician_cannot_validate(self):
        from django.contrib.auth.models import Group
        tech = User.objects.create_user("tech", password="x")
        tech.groups.add(Group.objects.get(role_code__code="TL"))
        self.client.force_login(tech)
        x = GeneXpertTest.objects.filter(result_status="DRAFT").first()
        r = self.client.post(reverse("diagnostic:genexpert_validate", args=[x.pk]))
        self.assertEqual(r.status_code, 403)

    def test_settings_pages_and_theme(self):
        from apps.core.models import UserProfile
        for section in ("profil", "apparence", "securite", "bug"):
            self.assertEqual(self.client.get(reverse("core:settings", args=[section])).status_code, 200)
        self.client.post(reverse("core:settings", args=["apparence"]), {"theme": "dark"})
        self.assertEqual(UserProfile.objects.get(user=self.admin).theme, "dark")
        r = self.client.get(reverse("core:dashboard"))
        self.assertContains(r, 'data-bs-theme="dark"')
        self.client.post(reverse("core:toggle_theme"), {"current": "dark", "next": "/"})
        self.assertEqual(UserProfile.objects.get(user=self.admin).theme, "light")

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="mycogen-test-"))
    def test_profile_photo_and_bug_report(self):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.core.models import BugReport, UserProfile
        buf = io.BytesIO()
        Image.new("RGB", (20, 20), "teal").save(buf, "PNG")
        photo = SimpleUploadedFile("moi.png", buf.getvalue(), content_type="image/png")
        self.client.post(reverse("core:settings", args=["profil"]),
                         {"first_name": "Hery", "last_name": "R", "email": "", "photo": photo})
        profile = UserProfile.objects.get(user=self.admin)
        self.assertTrue(profile.photo.name.startswith("avatars/"))
        r = self.client.get(profile.photo.url)  # média protégé, servi aux connectés
        self.assertEqual(r.status_code, 200)
        r.close()
        self.client.post(reverse("core:settings", args=["bug"]),
                         {"title": "Bouton", "severity": "LOW", "description": "x", "page": "/"})
        self.assertEqual(BugReport.objects.get().reporter, self.admin)
        self.assertEqual(self.client.get(reverse("core:support")).status_code, 200)

    def test_anonymous_reset_request(self):
        from apps.core.models import PasswordResetRequest
        self.client.logout()
        r = self.client.post(reverse("reset_request"), {"username": "ADMIN-TEST"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(PasswordResetRequest.objects.get().user, self.admin)
        self.client.post(reverse("reset_request"), {"username": "inexistant"})
        self.assertIsNone(PasswordResetRequest.objects.get(username="inexistant").user)

    def wizard_data(self, **extra):
        data = {"full_name": "RAZAFY Lalao", "birth_date": "1985-03-02", "sex": "F", "address": "Antanety",
                "patient_id": "", "facility": "", "requester": "Dr R", "code": Sample.next_code(),
                "sample_type": "SPUTUM", "type_detail": "2 mL", "collected_on": "2026-10-10",
                "received_at": "2026-10-11T09:00", "analyses": ["GNX-RIF", "FLUO-AUR"],
                "hiv_status": "NEG", "tb_history": "NEW", "phone": "034 00 000 00", "conform": "on"}
        data.update(extra)
        return data

    def test_register_wizard(self):
        from apps.core.models import Patient
        data = self.wizard_data(patient_id="1-260801-0001")
        r = self.client.post(reverse("core:register"), data)
        s = Sample.objects.get(code=data["code"])
        self.assertRedirects(r, s.get_absolute_url())
        self.assertEqual((s.patient.last_name, s.patient.first_name, s.patient.code), ("RAZAFY", "Lalao", "1-260801-0001"))
        self.assertEqual(s.requested_analyses, ["GNX-RIF", "FLUO-AUR"])
        self.assertEqual(s.analyses_display, "GNX-RIF, FLUO-AUR")
        self.assertEqual(s.type_display, "Crachat (2 mL)")
        # même ID patient → le patient existant est réutilisé
        self.client.post(reverse("core:register"), self.wizard_data(patient_id="1-260801-0001", code=Sample.next_code()))
        self.assertEqual(Patient.objects.filter(code="1-260801-0001").count(), 1)
        self.assertEqual(Patient.objects.get(code="1-260801-0001").samples.count(), 2)
        # lookup JSON
        j = self.client.get(reverse("core:patient_lookup"), {"id": "1-260801-0001"}).json()
        self.assertEqual((j["found"], j["samples"]), (True, 2))
        # fiche : analyses demandées sans résultat = « En attente » + bouton Saisir
        page = self.client.get(s.get_absolute_url()).content.decode()
        self.assertIn("En attente", page)
        self.assertIn("assay=ULTRA", page)
        self.assertIn("method=FM", page)  # FLUO-AUR → saisie microscopie pré-réglée en fluorescence

    def test_edit_reopens_wizard(self):
        s = Sample.objects.filter(patient__isnull=False).first()
        edit = reverse("core:register_edit", args=[s.pk])
        page = self.client.get(s.get_absolute_url()).content.decode()
        self.assertIn(edit, page)  # bouton Modifier → assistant
        self.assertIn("Préc.", page)
        r = self.client.get(edit)
        self.assertEqual(r.context["form"].initial["code"], s.code)
        data = self.wizard_data(code=s.code, patient_id=s.patient.code, full_name="RABE Hery Nirina",
                                conform="", non_conformity="Volume insuffisant")
        r = self.client.post(edit, data)
        self.assertRedirects(r, s.get_absolute_url())
        s.refresh_from_db()
        self.assertEqual((s.patient.first_name, s.patient.phone, s.status, s.conform, s.non_conformity),
                         ("Hery Nirina", "034 00 000 00", "REJECTED", False, "Volume insuffisant"))  # non conforme
        self.assertEqual(Sample.objects.filter(code=s.code).count(), 1)

    def test_validation_comment_and_documents(self):
        x = GeneXpertTest.objects.filter(result_status="DRAFT").first()
        self.client.post(reverse("diagnostic:genexpert_validate", args=[x.pk]),
                         {"validation_comment": "Concordant avec la microscopie"})
        x.refresh_from_db()
        self.assertEqual(x.validation_comment, "Concordant avec la microscopie")
        y = GeneXpertTest.objects.filter(result_status="DRAFT").first()
        self.client.post(reverse("core:validation"), {"items": [f"genexpert:{y.pk}"],
                                                      f"comment_genexpert:{y.pk}": "À recontrôler"})
        y.refresh_from_db()
        self.assertEqual((y.is_validated, y.validation_comment), (True, "À recontrôler"))
        for name in ("core:bench_sheet", "core:sample_report"):
            html = self.client.get(reverse(name, args=[x.sample.pk])).content.decode()
            self.assertIn("Concordant avec la microscopie", html)
            self.assertIn("Commentaire du validateur", html)

    def test_code_library_and_report(self):
        from apps.core.models import AnalysisCode
        from apps.diagnostic.models import Culture, Microscopy
        self.assertEqual(AnalysisCode.objects.get(code="Cult-LJ").meaning, "Culture sur LJ")
        s = Sample.objects.first()
        m = Microscopy.objects.create(sample=s, method="ZN", grade="2+")
        self.assertEqual(AnalysisCode.for_result(m).code, "ZN")
        c = Culture.objects.create(sample=s, medium="LJ", inoculated_on="2026-08-12", result="POSITIVE",
                                   result_date="2026-09-15", colony_count=12, ttp_days=99)
        self.assertEqual(c.ttp_days, 34)  # délai toujours recalculé à partir des dates
        # via le formulaire : le délai n'est plus saisissable et la date de résultat est exigée
        url = reverse("diagnostic:culture_update", args=[c.pk])
        self.assertNotIn("ttp_days", self.client.get(url).context["form"].fields)
        data = {"sample": s.pk, "medium": "LJ", "decontamination": "NALC", "inoculated_on": "2026-08-12",
                "result": "POSITIVE", "result_date": "", "tube_count": 2, "colony_count": 12}
        self.assertContains(self.client.post(url, data), "Indiquez la date du résultat")
        data["result_date"] = "2026-09-01"
        self.client.post(url, data)
        c.refresh_from_db()
        self.assertEqual(c.ttp_days, 20)
        data["result_date"] = "2026-09-15"
        self.client.post(url, data)
        c.refresh_from_db()
        self.assertEqual(c.ttp_days, 34)
        c.validate(self.admin, "OK")
        x = GeneXpertTest.objects.create(sample=s, assay="XDR", mtb_result="DETECTED", inh_result="DETECTED",
                                         fq_result="NOT_DETECTED")
        x.validate(self.admin)
        html = self.client.get(reverse("core:sample_report", args=[s.pk])).content.decode()
        self.assertIn("Logo_ipm.png", html)
        self.assertNotIn("PROJET / ÉTUDE", html)
        self.assertIn("15/09/2026", html)
        self.assertIn("12 colonies", html)
        self.assertIn(">R<", html.replace(" ", ""))
        page = self.client.get(s.get_absolute_url()).content.decode()
        self.assertIn(">ZN<", page)
        self.assertIn(">Cult-LJ<", page)
        self.assertNotIn('target="_blank"', page)
        self.assertEqual(self.client.get(reverse("core:code_list")).status_code, 200)

    def test_floor_plan(self):
        from apps.core import floorplan
        from apps.core.models import Room
        from apps.instruments.models import Instrument
        r = self.client.get(reverse("core:floorplan"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        # étage : 29 salles (12b et 12c fusionnées) ; RDC : 7 salles P3 + emplacement autoclave
        self.assertEqual(len(floorplan.LEVELS["etage"]["zones"]), 29)
        self.assertEqual(Room.objects.count(), 37)
        self.assertFalse(Room.objects.filter(zone="12c").exists())
        self.assertEqual(html.count('class="room assigned"'), 29)
        self.assertIn("?niveau=p3", html)   # escalier cliquable vers le RDC
        p3 = self.client.get(reverse("core:floorplan") + "?niveau=p3").content.decode()
        self.assertEqual(p3.count('class="room assigned"'), 8)
        self.assertIn("P3-04", p3)
        self.assertEqual(Room.objects.get(zone="P3-A").name, "Autoclave")
        auto = self.client.get(reverse("core:floorplan") + "?salle=P3-06")   # recherche → bon niveau
        self.assertEqual(auto.context["level"], "p3")
        self.assertEqual(sorted(Room.objects.filter(usage="SANIT").values_list("number", flat=True)), ["1", "2"])
        self.assertIn('stroke="#22a565"', html)  # portes coulissantes en vert
        self.assertIn(reverse("core:floorplan"), self.client.get(reverse("core:facility_list")).content.decode())
        # renseigner une salle + automate rattaché
        room = Room.objects.get(zone="12b")
        self.client.post(reverse("core:room_update", args=[room.pk]), {
            "number": "12b", "name": "Laboratoire GeneXpert", "zone": "12b", "usage": "MOL", "active": "on"})
        Instrument.objects.create(name="GX-4", kind="GENEXPERT", room=room)
        html = self.client.get(reverse("core:floorplan") + "?salle=12b").content.decode()
        self.assertIn("Laboratoire GeneXpert", html)
        self.assertIn("GX-4", html)  # dans les données de la fiche latérale
        # une zone ne peut porter qu'une salle
        r = self.client.post(reverse("core:room_create"), {"number": "99", "name": "x", "zone": "12b", "usage": "LAB"})
        self.assertContains(r, "existe déjà")
        self.assertEqual(self.client.get("/admin/core/room/").status_code, 200)

    def test_cbc_facility(self):
        from apps.core.models import Facility
        cbc = Facility.objects.get(code="CBC")
        self.assertEqual((cbc.name, cbc.get_type_display(), cbc.district), (
            "Centre de Biologie Clinique - IPM", "Centre de Biologie Clinique", "Antananarivo"))

    def test_register_errors(self):
        from apps.research.models import Project, Study
        existing = Sample.objects.first().code
        r = self.client.post(reverse("core:register"), self.wizard_data(code=existing, birth_date=""))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "existe déjà")
        self.assertEqual(r.context["step"], 1)
        r = self.client.post(reverse("core:register"), self.wizard_data(code="2026-1"))
        self.assertContains(r, "Format attendu")
        p1 = Project.objects.first()
        p2 = Project.objects.create(code="AUTRE", title="x", principal_investigator="y")
        st = Study.objects.create(project=p2, code="CBC")
        r = self.client.post(reverse("core:register"), self.wizard_data(project=p1.pk, study=st.pk))
        self.assertContains(r, "projet choisi")
        self.assertEqual(r.context["step"], 2)

    def test_study_case_configuration(self):
        from apps.research.models import Project, ProjectCase, Study
        p = Project.objects.create(code="CAS", title="x", principal_investigator="y")
        index, contact = (ProjectCase.objects.create(project=p, name=n) for n in ("Index", "Contact"))
        listed = Study.objects.create(project=p, code="L", case_mode="LIST")
        listed.cases.set([index])
        typed = Study.objects.create(project=p, code="T", case_mode="TEXT", case_label="N° d'inclusion")
        page = self.client.get(reverse("core:register")).content.decode()
        self.assertIn(f'data-mode="LIST" data-label="" data-cases="{index.pk}"', page)
        self.assertIn('data-label="N° d&#x27;inclusion"', page)
        # cas hors de la liste de l'étude → refusé
        r = self.client.post(reverse("core:register"), self.wizard_data(code="26-9101", project=p.pk,
                                                                        study=listed.pk, case=contact.pk))
        self.assertContains(r, "pas autorisé pour l&#x27;étude L")
        self.client.post(reverse("core:register"), self.wizard_data(code="26-9101", project=p.pk,
                                                                    study=listed.pk, case=index.pk))
        self.assertEqual(Sample.objects.get(code="26-9101").case, index)
        # étude à cas saisi : le texte est conservé, la liste ignorée
        self.client.post(reverse("core:register"), self.wizard_data(code="26-9102", project=p.pk, study=typed.pk,
                                                                    case=index.pk, case_text="INC-042"))
        s = Sample.objects.get(code="26-9102")
        self.assertEqual((s.case, s.case_text, s.case_display), (None, "INC-042", "INC-042"))
        self.assertIn("INC-042", self.client.get(s.get_absolute_url()).content.decode())
        # configuration : les cas d'une étude doivent appartenir à son projet
        other = ProjectCase.objects.create(project=Project.objects.exclude(pk=p.pk).first(), name="Autre")
        r = self.client.post(reverse("research:study_update", args=[listed.pk]), {
            "project": p.pk, "code": "L", "case_mode": "LIST", "cases": [other.pk], "active": "on"})
        self.assertContains(r, "doivent appartenir au projet CAS")

    def test_csv_export_utf8(self):
        raw = self.client.get(reverse("core:patient_list") + "?export=csv").content
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))      # BOM UTF-8 pour Excel
        text = raw.decode("utf-8")
        self.assertIn("Prénoms", text)
        self.assertNotIn("Ã", text)

    def test_validation_result_codes(self):
        from apps.core.models import AnalysisCode
        from apps.diagnostic.models import DST, Microscopy
        self.assertEqual(AnalysisCode.objects.get(code="GXTEL").category, "RESULT")
        self.assertNotIn("RIFND", AnalysisCode.catalog())          # pas proposé comme analyse demandable
        s = Sample.objects.first()
        GeneXpertTest.objects.create(sample=s, assay="ULTRA", mtb_result="MEDIUM", rif_result="NOT_DETECTED")
        GeneXpertTest.objects.create(sample=s, assay="XDR", mtb_result="VERY_HIGH", inh_result="DETECTED",
                                     fq_result="NOT_DETECTED", amk_result="INDETERMINATE")
        Microscopy.objects.create(sample=s, method="FM", grade="2+")
        DST.objects.create(sample=s, panel="FIRST", method="MGIT",
                           results={"STR": "S", "INH": "R", "RIF": "R", "EMB": "I", "PZA": "NF"})
        html = self.client.get(reverse("core:validation") + f"?q={s.code}").content.decode()
        for chip in (">GXMOY<", ">RIFND<", ">GXTEL<", ">INH R<", ">FLQ S<", ">AMK I<", ">200<", ">RIF R<",
                     ">STR S<", ">PZA NF<", 'rcode-alert" title="Éthambutol : Indéterminé">EMB I<'):
            self.assertIn(chip, html)
        self.assertIn('title="Isoniazide : Résistant"', html)
        self.assertIn("Résistance à la rifampicine Non Détectée", html)   # légende
        # un code désactivé dans la bibliothèque → retour au libellé en clair
        AnalysisCode.objects.filter(code="GXMOY").update(active=False)
        html = self.client.get(reverse("core:validation") + f"?q={s.code}").content.decode()
        self.assertNotIn(">GXMOY<", html)
        self.assertIn("MTB : MTB détecté — moyen", html)

    def test_validation_tabs_and_export(self):
        from apps.diagnostic.models import Culture
        s = Sample.objects.first()
        ultra = GeneXpertTest.objects.create(sample=s, assay="ULTRA", mtb_result="LOW", rif_result="DETECTED")
        xdr = GeneXpertTest.objects.create(sample=s, assay="XDR", mtb_result="HIGH", inh_result="DETECTED")
        lj = Culture.objects.create(sample=s, medium="LJ", inoculated_on="2026-09-01")
        mgit = Culture.objects.create(sample=s, medium="MGIT", inoculated_on="2026-09-01")
        url = reverse("core:validation")
        page = self.client.get(url).content.decode()
        for title in ("GeneXpert MTB/RIF Ultra", "GeneXpert XDR", "NPOC (Pluslife)", "Culture LJ", "Culture MGIT",
                      "Antibiogramme"):   # onglets toujours présents, même vides
            self.assertIn(title, page)
        tok = lambda o, p: f'value="{p}:{o.pk}"'
        html = self.client.get(url + "?analyse=gx-xdr").content.decode()
        self.assertIn(tok(xdr, "genexpert"), html)
        self.assertNotIn(tok(ultra, "genexpert"), html)
        html = self.client.get(url + "?analyse=culture-mgit").content.decode()
        self.assertIn(tok(mgit, "culture"), html)
        self.assertNotIn(tok(lj, "culture"), html)
        # export CSV : par test et global, UTF-8 avec BOM
        r = self.client.get(url + "?analyse=gx-ultra&export=csv")
        self.assertIn("validation_gx-ultra_", r["Content-Disposition"])
        self.assertTrue(r.content.startswith(b"\xef\xbb\xbf"))
        text = r.content.decode("utf-8-sig")
        self.assertTrue(text.startswith("Test;Code analyse;N° échantillon"))
        self.assertIn("GeneXpert MTB/RIF Ultra;GNX-RIF;", text)
        self.assertNotIn("GeneXpert XDR;", text)
        n_global = len(self.client.get(url + "?export=csv").content.decode("utf-8-sig").strip().splitlines())
        self.assertEqual(n_global - 1, GeneXpertTest.objects.filter(result_status="DRAFT").count()
                         + sum(c.model.objects.filter(result_status="DRAFT").count()
                               for c in __import__("apps.core.validation", fromlist=["x"]).validatable_cruds()
                               if c.prefix != "genexpert"))
        # statut « Validés » : résultats validés listés, sans case à cocher, exportables
        ultra.validate(self.admin, "OK")
        html = self.client.get(url + "?analyse=gx-ultra&statut=valides").content.decode()
        self.assertIn("bi-patch-check-fill", html)
        self.assertNotIn(tok(ultra, "genexpert"), html)
        text = self.client.get(url + "?analyse=gx-ultra&statut=valides&export=csv").content.decode("utf-8-sig")
        self.assertIn(";Validé;", text)
        self.assertIn(";OK", text)

    def test_sample_status_automatic(self):
        from apps.diagnostic.models import Culture, Microscopy
        self.client.post(reverse("core:register"), self.wizard_data(code="26-9201", analyses=["ZN", "Cult-LJ"]))
        s = Sample.objects.get(code="26-9201")
        self.assertEqual(s.status, "RECEIVED")                       # saisie faite
        m = Microscopy.objects.create(sample=s, method="ZN", grade="1+")
        s.refresh_from_db()
        self.assertEqual(s.status, "IN_PROGRESS")                    # culture pas encore commencée
        c = Culture.objects.create(sample=s, medium="LJ", inoculated_on="2026-09-01")
        s.refresh_from_db()
        self.assertEqual(s.status, "IN_PROGRESS")                    # culture en étuve, pas de résultat
        c.result, c.result_date = "NEGATIVE", "2026-10-20"
        c.save()
        s.refresh_from_db()
        self.assertEqual(s.status, "PENDING_VALIDATION")             # complet, non validé
        m.validate(self.admin)
        s.refresh_from_db()
        self.assertEqual(s.status, "PENDING_VALIDATION")
        c.validate(self.admin)
        s.refresh_from_db()
        self.assertEqual(s.status, "COMPLETED")                      # tout validé
        self.assertContains(self.client.get(s.get_absolute_url()), "Terminé")

    def test_dst_by_panel(self):
        from apps.diagnostic.models import DST
        s = Sample.objects.first()
        url = reverse("diagnostic:dst_create")
        form = self.client.get(url).content.decode()
        self.assertIn('name="res_STR"', form)
        self.assertIn('data-panel="SECOND"', form)
        base = {"sample": s.pk, "method": "MGIT", "panel": "FIRST", "test_date": "2026-10-20"}
        r = self.client.post(url, {**base, "res_STR": "S", "res_INH": "R"})
        self.assertContains(r, "Indiquez R, S, I, NF ou NA")       # RIF, EMB, PZA manquants
        r = self.client.post(url, {**base, "res_STR": "S", "res_INH": "R", "res_RIF": "R", "res_EMB": "NF",
                                   "res_PZA": "NA", "res_LFX": "S"})
        d = DST.objects.get(sample=s, panel="FIRST")
        self.assertEqual(d.results, {"STR": "S", "INH": "R", "RIF": "R", "EMB": "NF", "PZA": "NA"})
        self.assertEqual(d.resistant, ["INH", "RIF"])
        detail = self.client.get(d.get_absolute_url()).content.decode()
        self.assertIn("Isoniazide", detail)
        sheet = self.client.get(reverse("core:bench_sheet", args=[s.pk])).content.decode()
        self.assertIn("Première ligne (SIRE + PZA)", sheet)

    def test_validation_display_formats(self):
        from decimal import Decimal

        from apps.diagnostic.models import Culture, NPOCTest, Quantiferon
        s = Sample.objects.create(code="26-9301")
        Culture.objects.create(sample=s, medium="LJ", inoculated_on="2026-09-01", result="CONTAMINATED",
                               result_date="2026-09-20")
        Culture.objects.create(sample=s, medium="MGIT", inoculated_on="2026-09-01")
        Culture.objects.create(sample=s, medium="MGIT", inoculated_on="2026-09-01", result="POSITIVE",
                               result_date="2026-09-12")
        Quantiferon.objects.create(sample=s, nil=Decimal("9"), tb1=1, tb2=1, mitogen=5)
        NPOCTest.objects.create(sample=s, mtb_result="INVALID")
        NPOCTest.objects.create(sample=s, mtb_result="NOT_DETECTED")
        html = self.client.get(reverse("core:validation") + "?q=26-9301").content.decode()
        self.assertIn('class="rcode rcode-alert" title="Contaminée">Contaminée<', html)
        self.assertIn('class="rcode rcode-pending"', html)
        self.assertIn(">Positive<", html)
        self.assertIn('rcode-alert" title="Invalide">Indéterminé<', html)      # NPOC invalide
        self.assertIn('rcode-alert" title="Indéterminé">Indéterminé<', html)   # QFT (Nil > 8)
        self.assertIn('rcode-neg" title="MTB non détecté">Négatif<', html)
        self.assertNotIn("TTP", html)

    def test_validation_module_bulk(self):
        drafts = list(GeneXpertTest.objects.filter(result_status="DRAFT")[:3])
        r = self.client.post(reverse("core:validation"), {"items": [f"genexpert:{x.pk}" for x in drafts]})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(all(GeneXpertTest.objects.get(pk=x.pk).is_validated for x in drafts))
        page = self.client.get(reverse("core:validation") + "?analyse=genexpert").content.decode()
        self.assertNotIn(f"genexpert:{drafts[0].pk}\"", page)

    def test_documents_content(self):
        x = GeneXpertTest.objects.filter(mtb_result="TRACE").first() or GeneXpertTest.objects.first()
        x.validate(self.admin)
        sheet = self.client.get(reverse("core:bench_sheet", args=[x.sample.pk])).content.decode()
        self.assertIn("FICHE DE PAILLASSE", sheet)
        self.assertIn(x.sample.code, sheet)
        report = self.client.get(reverse("core:sample_report", args=[x.sample.pk])).content.decode()
        self.assertIn("COMPTE RENDU", report)
        self.assertIn("GENEXPERT RIF ULTRA", report)
        self.assertIn("GNX-RIF", report)

    def test_pdf_download(self):
        from unittest import skipUnless  # noqa: F401
        from apps.core.pdf import browser_path
        if not browser_path():
            self.skipTest("Edge/Chrome absent")
        s = Sample.objects.first()
        r = self.client.get(reverse("core:bench_sheet", args=[s.pk]) + "?format=pdf")
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))


class NavigationTests(TestCase):
    def test_sidebar_modules_and_hubs(self):
        from django.contrib.auth.models import User
        admin = User.objects.create_superuser("nav", "n@example.org", "x")
        self.client.force_login(admin)
        html = self.client.get(reverse("core:dashboard")).content.decode()
        sidebar = html[html.index('id="sidebar"'):html.index("</aside>")]
        for label in ("Échantillons", "Enregistrer", "Validation", "Structures / CDT",      # CNRM déplié
                      "Analyses TB", "Recherche", "Biobanque", "Automates", "Stock", "Qualité", "Administration"):
            self.assertIn(label, sidebar)
        for hidden in ("GeneXpert", "Microscopie", "Bioinformatique", "Diagnostic TB", "Pipelines"):
            self.assertNotIn(hidden, sidebar)
        hub = self.client.get(reverse("core:module", args=["research"])).content.decode()
        self.assertIn("Analyses génomiques", hub)     # bioinformatique intégrée à la recherche
        self.assertIn("Pipelines", hub)
        page = self.client.get(reverse("bioinfo:pipeline_list")).content.decode()
        self.assertIn('class="nav-item active" href="/m/research/"', page)
        self.assertIn("module-subnav", page)
        self.assertEqual(self.client.get(reverse("core:module", args=["inconnu"])).status_code, 404)
