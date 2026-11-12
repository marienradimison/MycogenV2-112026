import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.core.models import Facility, Patient, Sample
from apps.diagnostic.models import Culture, GeneXpertTest, Microscopy
from apps.research.models import Project, ProjectCase, Study


def sheet(i, sample_id, ipp, name, **extra):
    base = {
        "id": f"sheet-{i}", "createdAt": "2026-10-01T08:00:00.000Z", "updatedAt": f"2026-10-0{i}T08:00:00.000Z",
        "patientInfo": {"patientName": name, "patientDob": "1980-05-02", "patientAge": "46 ans", "patientSex": "F",
                        "patientAddress": "Lot II", "patientIpp": ipp, "patientPrescriber": "Dr R",
                        "patientCdt": "BEFELATANANA SMR"},
        "sampleInfo": {"sampleId": sample_id, "sampleType": "Crachat", "sampleTypePrecision": "",
                       "dateCollection": "2026-10-01", "dateReceipt": "2026-10-02"},
        "pnltStudy": {"tbDiag": False, "tbmrDiag": True, "suiviTbmr": False, "subType": "rechute", "moisSuivi": ""},
        "analysisTypes": {}, "project": "PNLT",
        "examRequests": {"checkMicro": True, "checkGexpert": True, "checkCulture": True},
        "microResults": {"microDateManip": "2026-10-02", "microDateRendu": "2026-10-03", "microResult": "Positif (2+)"},
        "gexpertResults": {"gexpertDateManip": "2026-10-02", "gexpertDateRendu": "",
                           "gexpertMtb": "Détecté (Faible)", "gexpertRif": "Non détectée (Sensible)"},
        "cultureResults": {"cultureDateEnsemencement": "2026-10-03", "cultureResult": "En cours",
                           "cultureIdentification": "Non Applicable", "cultureColoniesType": "0"},
        "qftResults": {}, "gexpertXdrResults": {}, "antibiogrammeResults": {}, "commentField": "",
        "validatorSignature": "data:image/png;base64,AAAA",
    }
    base.update(extra)
    return base


class LegacyImportTests(TestCase):
    def setUp(self):
        self.fac = Facility.objects.create(code="T2", name="SMR Befelatanana")
        pnlt = Project.objects.create(code="PNLT", title="PNLT", principal_investigator="x")
        study = Study.objects.create(project=pnlt, code="TBMR", case_mode="LIST")
        study.cases.add(ProjectCase.objects.create(project=pnlt, name="Rechute"))
        self.dir = Path(tempfile.mkdtemp())
        sheets = [
            sheet(1, "26.3001", "01/26", "RAKOTO Jean"),
            sheet(2, "26-3001", "01/26", "RAKOTO Jean"),                     # même échantillon, plus récente
            sheet(3, "2026-3002", "01/26", "RABE Paul",                     # même identifiant, autre personne
                  cultureResults={"cultureDateEnsemencement": "2026-09-01", "cultureDateSortie": "2026-10-01",
                                  "cultureDateRendu": "2026-10-02", "cultureResult": "Positive",
                                  "cultureIdentification": "CMTB", "cultureColoniesType": "exact",
                                  "cultureColoniesExact": "12"}),
            sheet(4, "I-669", "", "X"),                                      # n° illisible
        ]
        self.json = self.dir / "export.json"
        self.json.write_text(json.dumps(sheets), encoding="utf-8")

    def run_import(self, *args):
        call_command("import_legacy", str(self.json), *args, stdout=open(self.dir / "out.txt", "w", encoding="utf-8"))

    def test_dry_run_then_import_then_rerun(self):
        self.run_import("--dry-run")
        self.assertFalse(Sample.objects.exists())
        mapping = (self.dir / "correspondance_provenances.csv").read_text(encoding="utf-8-sig")
        self.assertIn("BEFELATANANA SMR;4;;;T2;SMR Befelatanana", mapping)   # proposition, non appliquée
        self.run_import()
        self.assertEqual(sorted(Sample.objects.values_list("code", flat=True)), ["26-3001", "26-3002"])
        s1, s2 = Sample.objects.get(code="26-3001"), Sample.objects.get(code="26-3002")
        self.assertEqual(s1.legacy_ref, "sheet-2")
        self.assertIsNone(s1.facility)
        self.assertIn("Provenance (ancien LIMS) : BEFELATANANA SMR", s1.notes)
        self.assertEqual((s1.study.code, s1.case.name, s1.requested_analyses), ("TBMR", "Rechute", ["FLUO-AUR", "GNX-RIF", "Cult-LJ"]))
        # identifiant partagé par deux personnes : deux patients distincts, même identifiant externe
        self.assertNotEqual(s1.patient, s2.patient)
        self.assertEqual((s1.patient.code, s2.patient.code), ("01/26", "01/26"))
        # résultats : rendu = validé, non rendu = à valider ; culture en cours en étuve
        m = Microscopy.objects.get(sample=s1)
        self.assertEqual((m.grade, m.result_status, str(timezone.localtime(m.validated_at).date())), ("2+", "VALIDATED", "2026-10-03"))
        self.assertEqual(GeneXpertTest.objects.get(sample=s1).result_status, "DRAFT")
        self.assertEqual(Culture.objects.get(sample=s1).result, "PENDING")
        c2 = Culture.objects.get(sample=s2)
        self.assertEqual((c2.result, c2.identification, c2.colony_count, int(c2.ttp_days)), ("POSITIVE", "MTBC", 12, 30))
        s1.refresh_from_db()
        self.assertEqual(s1.status, "IN_PROGRESS")
        report = (self.dir / "import_rapport.csv").read_text(encoding="utf-8-sig")
        self.assertIn("sheet-1;26-3001;DOUBLON", report)
        self.assertIn("sheet-4;;IGNORÉE", report)
        # relance après validation de la correspondance : rien n'est dupliqué, la provenance est complétée
        path = self.dir / "correspondance_provenances.csv"
        path.write_text(path.read_text(encoding="utf-8-sig").replace("BEFELATANANA SMR;4;;", "BEFELATANANA SMR;4;T2;"),
                        encoding="utf-8-sig")
        self.run_import()
        self.assertEqual(Sample.objects.count(), 2)
        self.assertEqual(Patient.objects.count(), 2)
        s1.refresh_from_db()
        self.assertEqual(s1.facility, self.fac)
        self.assertNotIn("Provenance (ancien LIMS)", s1.notes)

    def test_replace_with_latest_export(self):
        from django.contrib.auth.models import User
        from django.core.management.base import CommandError
        self.run_import()
        self.assertEqual(Culture.objects.get(sample__code="26-3001").result, "PENDING")
        # l'ancien LIMS a continué : la culture de 26-3001 est sortie négative entre-temps
        sheets = json.loads(self.json.read_text(encoding="utf-8"))
        sheets[1]["cultureResults"].update({"cultureResult": "Négative", "cultureDateSortie": "2026-12-31",
                                            "cultureDateRendu": "2026-12-31"})
        self.json.write_text(json.dumps(sheets), encoding="utf-8")
        self.run_import()                                   # sans --replace : fiche ignorée, non mise à jour
        self.assertEqual(Culture.objects.get(sample__code="26-3001").result, "PENDING")
        self.run_import("--replace")
        self.assertEqual(Culture.objects.get(sample__code="26-3001").result, "NEGATIVE")
        self.assertEqual((Sample.objects.count(), Patient.objects.count()), (2, 2))
        # une fiche complétée dans MYCOGEN bloque le remplacement
        m = Microscopy.objects.get(sample__code="26-3001")
        m.updated_by = User.objects.create_user("tech")
        m.save()
        with self.assertRaises(CommandError):
            self.run_import("--replace")
        self.assertEqual(Sample.objects.count(), 2)
