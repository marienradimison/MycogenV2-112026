import socket
import threading

from django.test import TransactionTestCase

from apps.core.models import Sample
from apps.diagnostic.models import Culture, GeneXpertTest

from . import astm
from .handlers import classify_genexpert, handle_astm, parse_ttp_days
from .models import Instrument, InstrumentMessage

# Message de résultat au format ASTM du logiciel GeneXpert Dx (délimiteurs @ ^ \)
GX_ULTRA = "\r".join([
    r"H|@^\|URM-Bz4dWyR3-01||GeneXpert PC^GeneXpert^6.4|||||LIS||P|1394-97|20261011093012",
    "P|1",
    "O|1|{sid}||^^^MTB-RIF Ultra|R|20261011080000|||||||||ORH||||||||||F",
    "R|1|^MTB-RIF Ultra^^MTB-RIF Ultra^Xpert MTB-RIF Ultra^4^MTB^|MTB DETECTED MEDIUM^|||||F||Rakoto"
    "|20261011080102|20261011093000|Cepheid^811234^^GX4-A^Module 2",
    "R|2|^MTB-RIF Ultra^^MTB-RIF Ultra^Xpert MTB-RIF Ultra^4^Rif Resistance^|Rif Resistance DETECTED^|||||F",
    "R|3|^MTB-RIF Ultra^^MTB-RIF Ultra^Xpert MTB-RIF Ultra^4^SPC^Ct|25.4|||||F",
    "L|1|F",
]) + "\r"

GX_XDR = "\r".join([
    r"H|@^\|X||GeneXpert PC^GeneXpert^6.4|||||LIS||P|1394-97|20261011093012",
    "P|1",
    "O|1|{sid}||^^^MTB-XDR|R",
    "R|1|^MTB-XDR^^^^^MTB^|MTB DETECTED^|||||F",
    "R|2|^MTB-XDR^^^^^INH^|INH Resistance DETECTED^|||||F",
    "R|3|^MTB-XDR^^^^^FLQ^|FLQ Resistance NOT DETECTED^|||||F",
    "R|4|^MTB-XDR^^^^^AMK^|AMK Resistance NOT DETECTED^|||||F",
    "R|5|^MTB-XDR^^^^^ETH^|ETH Resistance INDETERMINATE^|||||F",
    "L|1|F",
]) + "\r"


class AstmTests(TransactionTestCase):
    def test_frames_roundtrip(self):
        msg = GX_ULTRA.format(sid="X")
        frames = astm.build_frames(msg)
        self.assertEqual(len(frames), len([r for r in msg.split("\r") if r]) + 0)  # 1 trame / enregistrement
        text = "".join(astm.parse_frame(f)[0] for f in frames)
        self.assertEqual(text, msg)

    def test_bad_checksum(self):
        frame = bytearray(astm.build_frames("H|\\^&\r")[0])
        frame[-4] = ord("0") if frame[-4] != ord("0") else ord("1")
        with self.assertRaises(ValueError):
            astm.parse_frame(bytes(frame))

    def test_long_record_split_with_etb(self):
        msg = "H|\\^&\rC|1||" + "x" * 600 + "\rL|1|N\r"
        frames = astm.build_frames(msg)
        self.assertTrue(any(f[-5:-4] == astm.ETB for f in frames))
        self.assertEqual("".join(astm.parse_frame(f)[0] for f in frames), msg)

    def test_parse_delimiters(self):
        recs = astm.parse_message(GX_ULTRA.format(sid="MYC26-00001"))
        o = next(r for r in recs if r.type == "O")
        self.assertEqual(o.component(3, 0), "MYC26-00001")
        self.assertEqual(o.d["repeat"], "@")

    def test_classify(self):
        self.assertEqual(classify_genexpert(["MTB DETECTED VERY LOW", "Rif Resistance INDETERMINATE"]),
                         {"mtb_result": "VERY_LOW", "rif_result": "INDETERMINATE"})
        self.assertEqual(classify_genexpert(["MTB NOT DETECTED"]), {"mtb_result": "NOT_DETECTED"})
        self.assertEqual(classify_genexpert(["MTB DETECTED TRACE;Rif Resistance NOT DETECTED"]),
                         {"mtb_result": "TRACE", "rif_result": "NOT_DETECTED"})
        self.assertEqual(classify_genexpert(["INVALID"]), {"mtb_result": "INVALID"})
        self.assertEqual(classify_genexpert(["MTB DETECTED VERY HIGH"]), {"mtb_result": "VERY_HIGH"})
        self.assertEqual(classify_genexpert(["MTB DETECTED HIGH"]), {"mtb_result": "HIGH"})

    def test_ttp(self):
        self.assertEqual(parse_ttp_days("12d 6h"), 12.2)
        self.assertEqual(parse_ttp_days("12/06"), 12.2)
        self.assertEqual(parse_ttp_days("240"), 10.0)


class GeneXpertImportTests(TransactionTestCase):
    def setUp(self):
        self.gx = Instrument.objects.create(name="GX4", kind="GENEXPERT", port=0)
        self.sample = Sample.objects.create()

    def test_ultra_import(self):
        handle_astm(self.gx, GX_ULTRA.format(sid=self.sample.code))
        t = GeneXpertTest.objects.get(sample=self.sample)
        self.assertEqual((t.assay, t.mtb_result, t.rif_result), ("ULTRA", "MEDIUM", "DETECTED"))
        self.assertEqual(t.result_status, "DRAFT")  # validation biologiste toujours requise
        self.assertIn("Module 2", t.instrument)
        self.assertEqual(str(t.test_date), "2026-10-11")
        self.sample.refresh_from_db()
        self.assertEqual(self.sample.status, "PENDING_VALIDATION")   # résultat reçu, à valider

    def test_xdr_import(self):
        handle_astm(self.gx, GX_XDR.format(sid=self.sample.code))
        t = GeneXpertTest.objects.get(sample=self.sample)
        self.assertEqual((t.assay, t.mtb_result, t.inh_result, t.fq_result, t.amk_result, t.eto_result),
                         ("XDR", "DETECTED", "DETECTED", "NOT_DETECTED", "NOT_DETECTED", "INDETERMINATE"))

    def test_duplicate_and_unknown_sample(self):
        handle_astm(self.gx, GX_ULTRA.format(sid=self.sample.code))
        handle_astm(self.gx, GX_ULTRA.format(sid=self.sample.code))
        self.assertEqual(GeneXpertTest.objects.count(), 1)
        self.assertTrue(InstrumentMessage.objects.filter(status="DUPLICATE").exists())
        handle_astm(self.gx, GX_ULTRA.format(sid="INCONNU-1"))
        self.assertTrue(InstrumentMessage.objects.filter(status="UNMATCHED", sample_ref="INCONNU-1").exists())

    def test_host_query_logged_and_answered(self):
        reply = handle_astm(self.gx, f"H|@^\\|||GeneXpert\rQ|1|^{self.sample.code}||ALL||||||||O\rL|1|N\r")
        self.assertIn("L|1|I", reply)
        q = InstrumentMessage.objects.get(kind="QUERY")
        self.assertEqual(q.sample, self.sample)

    def test_mgit_update_existing_culture(self):
        mgit = Instrument.objects.create(name="MGIT-1", kind="MGIT", port=0)
        c = Culture.objects.create(sample=self.sample, medium="MGIT", inoculated_on="2026-10-01")
        handle_astm(mgit, "\r".join([
            "H|\\^&|||BACTEC MGIT 960", "P|1", f"O|1|{self.sample.code}|430001234|^^^MGIT_TB",
            "R|1|^^^GND_MGIT^STATUS|INST_POSITIVE|||||F", "R|2|^^^GND_MGIT^TTP|9d 12h|||||F", "L|1|N"]))
        c.refresh_from_db()
        from django.utils import timezone
        self.assertEqual(c.result, "POSITIVE")
        self.assertEqual(c.result_date, timezone.localdate())
        self.assertEqual(int(c.ttp_days), (timezone.localdate() - c.inoculated_on).days)


class PagesTest(TransactionTestCase):
    def test_monitor_and_queue_pages(self):
        from django.contrib.auth.models import User
        from django.urls import reverse

        gx = Instrument.objects.create(name="GX4", kind="GENEXPERT", port=12000)
        sample = Sample.objects.create()
        handle_astm(gx, f"H|@^\\|\rQ|1|^{sample.code}||ALL\rL|1|N\r")
        handle_astm(gx, GX_ULTRA.format(sid="INCONNU-9"))
        self.client.force_login(User.objects.create_superuser("a", "a@example.org", "x"))
        for url in [reverse("instruments:monitor"), reverse("instruments:message_list") + "?status=todo"]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
        self.assertContains(self.client.get(reverse("instruments:monitor")), sample.code)
        msg = InstrumentMessage.objects.get(status="UNMATCHED")
        self.assertEqual(self.client.get(msg.get_absolute_url()).status_code, 200)
        # association manuelle à un échantillon existant → import
        self.client.post(reverse("instruments:message_action", args=[msg.pk]),
                         {"action": "assign", "sample_code": sample.code})
        msg.refresh_from_db()
        self.assertEqual(msg.status, "IMPORTED")
        self.assertEqual(GeneXpertTest.objects.get(sample=sample).mtb_result, "MEDIUM")


class LiveModulePagesTest(TransactionTestCase):
    def test_genexpert_and_npoc_live(self):
        from django.contrib.auth.models import User
        from django.urls import reverse

        gx = Instrument.objects.create(name="GX-IV Labo 7", kind="GENEXPERT", port=12000)
        running = Sample.objects.create(requested_analyses=["GNX-XDR"])
        handle_astm(gx, f"H|@^\\|\rQ|1|^{running.code}||ALL\rL|1|N\r")       # test démarré
        done = Sample.objects.create()
        handle_astm(gx, GX_ULTRA.format(sid=done.code))                       # résultat reçu
        self.client.force_login(User.objects.create_superuser("a", "a@example.org", "x"))

        r = self.client.get(reverse("diagnostic:genexpert_live"))
        html = r.content.decode()
        self.assertEqual(r.context["stats"]["running"], 1)
        self.assertEqual(r.context["instruments"][0]["running"][0]["duration"], 90)  # XDR demandé
        self.assertIn(running.code, html)
        self.assertIn("progress-bar", html)
        self.assertIn(done.code, html)                       # derniers résultats
        self.assertIn(reverse("diagnostic:genexpert_list"), html)   # onglet « Tests réalisés »
        partial = self.client.get(reverse("diagnostic:genexpert_live") + "?partial=1").content.decode()
        self.assertNotIn("<html", partial)
        lst = self.client.get(reverse("diagnostic:genexpert_list")).content.decode()
        self.assertIn(reverse("diagnostic:genexpert_live"), lst)   # onglet « Suivi en temps réel »
        self.assertIn('class="nav-item active" href="/m/analyses/"', lst)  # module Analyses TB actif
        self.assertIn('class="subnav-item active" href="/diagnostic/genexpert/suivi/"', lst)  # sous-module actif
        self.assertEqual(self.client.get(reverse("diagnostic:npoc_live")).status_code, 200)


class SocketSessionTest(TransactionTestCase):
    """Dialogue ASTM complet sur TCP : ENQ/ACK, trames, EOT."""

    def test_tcp_session(self):
        gx = Instrument.objects.create(name="GX-TCP", kind="GENEXPERT", port=0)
        sample = Sample.objects.create()
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def serve():
            conn, _ = server.accept()
            session = astm.Session(astm.SocketLink(conn, timeout=2), lambda t: handle_astm(gx, t))
            try:
                session.run()
            except (ConnectionError, OSError):
                pass

        th = threading.Thread(target=serve, daemon=True)
        th.start()
        client = socket.create_connection(("127.0.0.1", port))
        client.settimeout(5)
        client.sendall(astm.ENQ)
        self.assertEqual(client.recv(1), astm.ACK)
        for frame in astm.build_frames(GX_ULTRA.format(sid=sample.code)):
            client.sendall(frame)
            self.assertEqual(client.recv(1), astm.ACK)
        client.sendall(astm.EOT)
        client.close()
        th.join(timeout=5)
        server.close()
        self.assertEqual(GeneXpertTest.objects.get(sample=sample).mtb_result, "MEDIUM")
