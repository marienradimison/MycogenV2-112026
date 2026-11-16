import tempfile
from decimal import Decimal as D

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.crud import REGISTRY
from apps.core.models import Sample
from apps.diagnostic.models import GeneXpertTest, Quantiferon
from apps.research.models import PCRAssay, PCRRun


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
        run = PCRRun.objects.create(run_id="PCR-1", assay="SWEENEY3", threshold=D("-3"))
        p = PCRAssay.objects.create(sample=s, run=run, ct_gbp5=D("25"), ct_dusp3=D("27"), ct_klf2=D("24"))
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
        first = s.patient
        # même identifiant, patient choisi → nouvel échantillon rattaché au même patient
        self.client.post(reverse("core:register"), self.wizard_data(patient_id="1-260801-0001", code=Sample.next_code(),
                                                                    patient_pk=first.pk))
        self.assertEqual(first.samples.count(), 2)
        # même identifiant, « nouveau patient » → deux patients distincts avec le même identifiant
        self.client.post(reverse("core:register"), self.wizard_data(
            patient_id="1-260801-0001", code=Sample.next_code(), patient_pk="new", full_name="RABE Hery"))
        self.assertEqual(Patient.objects.filter(code="1-260801-0001").count(), 2)
        self.assertEqual(first.samples.count(), 2)
        # recherche : tous les patients ayant cet identifiant, puis fiche complète du patient choisi
        j = self.client.get(reverse("core:patient_lookup"), {"id": "1-260801-0001"}).json()
        self.assertEqual((j["found"], len(j["matches"])), (True, 2))
        self.assertEqual(next(m for m in j["matches"] if m["pk"] == first.pk)["samples"], 2)
        j = self.client.get(reverse("core:patient_lookup"), {"pk": first.pk}).json()
        self.assertEqual((j["full_name"], j["patient_pk"]), ("RAZAFY Lalao", str(first.pk)))
        # historique depuis la fiche : les échantillons de ce patient seulement
        page = self.client.get(s.get_absolute_url()).content.decode()
        self.assertIn(f"?patient={first.pk}", page)
        self.assertEqual(len(self.client.get(reverse("core:sample_list") + f"?patient={first.pk}").context["object_list"]), 2)
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
                                   "res_PZA": "NA", "res_LEV": "S"})
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

    def test_sample_table_and_export(self):
        from apps.diagnostic.models import DST
        self.client.post(reverse("core:register"), self.wizard_data(
            code="26-9401", analyses=["GNX-RIF"], aspect="Muco-purulent", requester_contact="034 11 222 33",
            host="Bovin"))
        s = Sample.objects.get(code="26-9401")
        self.assertEqual((s.aspect, s.requester_contact), ("Muco-purulent", "034 11 222 33"))
        GeneXpertTest.objects.create(sample=s, assay="ULTRA", mtb_result="HIGH", rif_result="DETECTED").validate(self.admin)
        DST.objects.create(sample=s, method="MGIT", panel="FIRST",
                           results={"STR": "S", "INH": "R", "RIF": "R", "EMB": "NF", "PZA": "NA"})
        lst = self.client.get(reverse("core:sample_list")).content.decode()
        for col in ("Identifiant externe", "Date de réception", "Projet", "Étude", "Cas", "Statut"):
            self.assertIn(col, lst)
        self.assertNotIn("Analyses demandées", lst)
        self.assertIn('aspect-options', self.client.get(reverse("core:register")).content.decode())
        raw = self.client.get(reverse("core:sample_list") + "?q=26-9401&export=csv").content
        self.assertTrue(raw.startswith(bytes.fromhex("efbbbf")))   # BOM UTF-8
        head, line = raw.decode("utf-8-sig").splitlines()[:2]
        row = dict(zip(head.split(";"), line.split(";")))
        self.assertTrue(head.startswith("N° échantillon;Identifiant externe;Nom et Prénom;Date de naissance;Age;Sexe"))
        self.assertEqual((row["N° échantillon"], row["Contact Prescripteur"], row["Aspect"], row["Forme"], row["Hôte"]),
                         ("26-9401", "034 11 222 33", "Muco-purulent", "Pulmonaire", "Bovin"))
        self.assertEqual((row["GNX-RIF"], row["Resistance RIF"]), ("ELEVE", "DETECTEE"))
        self.assertNotEqual(row["Date rendu GNX-RIF"], "NA")
        self.assertEqual((row["DST-MGIT-INH"], row["DST-MGIT-STR"], row["DST-MGIT-EMB"]), ("RESISTANT", "SENSIBLE", "NON FAIT"))
        self.assertEqual((row["Cult-LJ"], row["QFT"], row["GNX-XDR"], row["Volume (mL)"]), ("NA", "NA", "NA", "NA"))
        self.assertNotIn("", row.values())   # non renseigné → NA

    def test_export_region_from_facility(self):
        from apps.core.models import Facility, Patient
        cdt = Facility.objects.create(code="T999", name="CDT test", region="ANOSY")
        patient = Patient.objects.create(last_name="TEST", sex="M", region="ANALAMANGA")
        Sample.objects.create(code="26-9501", patient=patient, facility=cdt)
        head, line = self.client.get(reverse("core:sample_list") + "?q=26-9501&export=csv").content.decode("utf-8-sig").splitlines()[:2]
        self.assertEqual(dict(zip(head.split(";"), line.split(";")))["Région"], "ANOSY")

    def test_validation_sorted_by_rendered_date(self):
        from apps.diagnostic.models import Culture, Microscopy
        s = Sample.objects.create(code="26-9502")
        old = Microscopy.objects.create(sample=s, method="ZN", grade="1+", test_date="2026-01-10")
        recent = Culture.objects.create(sample=s, medium="MGIT", inoculated_on="2025-12-01", result="NEGATIVE",
                                        result_date="2026-03-01")
        middle = GeneXpertTest.objects.create(sample=s, assay="ULTRA", mtb_result="LOW", test_date="2026-02-01")
        pending = Culture.objects.create(sample=s, medium="MGIT", inoculated_on="2026-04-01")
        rows = self.client.get(reverse("core:validation") + "?q=26-9502").context["rows"]
        self.assertEqual([r["obj"] for r in rows], [recent, middle, old, pending])   # sans date de rendu : en bas
        self.assertEqual(str(rows[0]["rendered"]), "2026-03-01")

    def test_culture_lists_by_medium(self):
        from apps.diagnostic.models import Culture
        s = Sample.objects.create(code="26-9503")
        Culture.objects.create(sample=s, medium="MGIT", inoculated_on="2026-05-01")
        Culture.objects.create(sample=s, medium="MGIT", inoculated_on="2026-05-02")
        Culture.objects.create(sample=s, medium="LJ", inoculated_on="2026-05-01")
        url = reverse("diagnostic:culture_list") + "?medium=MGIT"
        r = self.client.get(url + "&q=26-9503")
        html = r.content.decode()
        self.assertEqual(len(r.context["object_list"]), 2)
        self.assertNotIn("Milieu", html)                                   # ni colonne ni filtre
        self.assertIn("<h1>Culture MGIT</h1>", html)
        self.assertIn('name="inoculated_on"', html)
        self.assertIn('<input type="hidden" name="medium" value="MGIT">', html)
        self.assertEqual(len(self.client.get(url + "&q=26-9503&inoculated_on=2026-05-02").context["object_list"]), 1)
        csv_text = self.client.get(url + "&q=26-9503&export=csv").content.decode("utf-8-sig")
        self.assertIn("Milieu", csv_text.splitlines()[0])                  # toujours présent dans l'export
        self.assertEqual(len(csv_text.strip().splitlines()), 3)

    def test_analysis_pages_without_module_name(self):
        for url in (reverse("diagnostic:lj_home"), reverse("diagnostic:genexpert_live"),
                    reverse("diagnostic:microscopy_list")):
            self.assertNotIn('class="subnav-module"', self.client.get(url).content.decode())
            self.assertNotIn('text-muted">Analyses TB<', self.client.get(url).content.decode())

    def test_runs_list_their_samples(self):
        from apps.research.models import PCRAssay, PCRRun, SequencingLibrary, SequencingRun
        s1, s2 = Sample.objects.create(code="26-9601"), Sample.objects.create(code="26-9602")
        run = SequencingRun.objects.create(run_id="ONT-T1", platform="ONT_MINION")
        for i, s in enumerate((s1, s2)):
            SequencingLibrary.objects.create(run=run, sample=s, library_id=f"L{i}")
        html = self.client.get(run.get_absolute_url()).content.decode()
        self.assertIn("Échantillons analysés", html)
        for code in (s1.code, s2.code):
            self.assertIn(code, html)
        # PCR : le run porte la signature et le seuil ; le formulaire ne demande que l'échantillon et les Ct
        r = self.client.post(reverse("research:pcrrun_create"), {
            "run_id": "PCR-T1", "assay": "SWEENEY3", "threshold": "-3", "run_date": "2026-06-01", "status": "DONE"})
        pcr_run = PCRRun.objects.get(run_id="PCR-T1")
        self.assertEqual(r.status_code, 302)
        add = reverse("research:pcr_create") + f"?run={pcr_run.pk}"
        self.assertEqual(self.client.get(add).context["form"].initial["run"], str(pcr_run.pk))
        self.client.post(add, {"run": pcr_run.pk, "sample": s1.pk, "ct_gbp5": "25", "ct_dusp3": "27", "ct_klf2": "24"})
        p = PCRAssay.objects.get(run=pcr_run)
        self.assertEqual((p.score, p.outcome, str(p.test_date)), (D("-2.000"), "POS", "2026-06-01"))
        html = self.client.get(pcr_run.get_absolute_url()).content.decode()
        self.assertIn(s1.code, html)
        self.assertIn("Ct GBP5", html)
        self.assertNotIn("Ct GBP2", html)                                  # gènes RISK6 masqués
        # seuil corrigé sur le run → conclusion recalculée
        pcr_run.threshold = D("0")
        pcr_run.save()
        p.refresh_from_db()
        self.assertEqual(p.outcome, "NEG")
        self.assertContains(self.client.get(reverse("core:validation") + "?q=26-9601"), "Sweeney3")
        # menu : Runs de séquençage et Runs PCR ; plus de liste par librairie
        page = self.client.get(reverse("research:run_list")).content.decode()
        self.assertIn("Runs PCR", page)
        self.assertNotIn(">Librairies<", page)

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
