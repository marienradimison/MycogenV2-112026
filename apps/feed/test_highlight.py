import base64
import shutil
import tempfile

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Highlight, PollOption, Post

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
MEDIA = tempfile.mkdtemp(prefix="mycogen-test-media-")


@override_settings(MEDIA_ROOT=MEDIA)
class HighlightTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_mycogen", verbosity=0)
        cls.cds = User.objects.create_user("chef", password="x", first_name="Voahangy")
        cls.cds.groups.add(Group.objects.get(role_code__code="CDS"))
        cls.tl = User.objects.create_user("tech", password="x", first_name="Hery")
        cls.tl.groups.add(Group.objects.get(role_code__code="TL"))

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def test_dashboard_replaces_org_chart(self):
        self.client.force_login(self.tl)
        page = self.client.get(reverse("core:dashboard"))
        self.assertContains(page, "À la une")
        self.assertNotContains(page, "Organigramme")
        self.assertContains(page, "Rien à la une")

    def test_feature_post_then_edit_anytime(self):
        post = Post.objects.create(author=self.tl, text="Formation biosécurité P3 jeudi à 9 h",
                                   photo=SimpleUploadedFile("affiche.png", PNG, content_type="image/png"))
        self.client.force_login(self.tl)
        self.assertNotContains(self.client.get(reverse("feed:feed")), reverse("feed:feature", args=[post.pk]))
        self.assertEqual(self.client.post(reverse("feed:feature", args=[post.pk])).status_code, 403)
        self.client.force_login(self.cds)
        self.assertContains(self.client.get(reverse("feed:feed")), reverse("feed:feature", args=[post.pk]))
        r = self.client.post(reverse("feed:feature", args=[post.pk]))
        self.assertTrue(r.json()["reload_page"])
        h = Highlight.objects.get(current=True)
        self.assertEqual((h.text, h.post), (post.text, post))
        self.assertTrue(h.image)                                         # copie de la photo
        self.assertContains(self.client.get(reverse("feed:feed")), "bi-star-fill")   # badge « À la une »
        dash = self.client.get(reverse("core:dashboard"))
        self.assertContains(dash, "Formation biosécurité P3")
        self.assertContains(dash, "Publié par Hery")
        # modification à tout moment
        r = self.client.post(reverse("feed:highlight_edit", args=[h.pk]), {
            "title": "Formation P3 reportée", "text": "Nouvelle date : vendredi 10 h", "link": "/recherche/mycolearn/"})
        self.assertRedirects(r, reverse("core:dashboard"))
        dash = self.client.get(reverse("core:dashboard"))
        self.assertContains(dash, "Formation P3 reportée")
        self.assertContains(dash, 'href="/recherche/mycolearn/"')
        # la publication supprimée, la « À la une » reste
        post.delete()
        h.refresh_from_db()
        self.assertTrue(h.current)
        self.assertIsNone(h.post)

    def test_new_highlight_history_and_link_validation(self):
        self.client.force_login(self.cds)
        r = self.client.post(reverse("feed:highlight_new"), {"title": "Bienvenue", "text": "", "link": "javascript:alert(1)"})
        self.assertContains(r, "Indiquez une adresse")
        self.client.post(reverse("feed:highlight_new"), {"title": "Première"})
        self.client.post(reverse("feed:highlight_new"), {"title": "Seconde"})
        first, second = Highlight.objects.get(title="Première"), Highlight.objects.get(title="Seconde")
        self.assertEqual((first.current, second.current), (False, True))   # une seule à la une
        self.client.post(reverse("feed:highlight_state", args=[first.pk]), {"action": "show"})
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.current, second.current), (True, False))
        self.client.post(reverse("feed:highlight_state", args=[first.pk]), {"action": "hide"})
        self.assertContains(self.client.get(reverse("core:dashboard")), "Rien à la une")
        self.client.force_login(self.tl)
        self.assertEqual(self.client.get(reverse("feed:highlight_new")).status_code, 403)

    def test_poll_and_challenge_are_interactive_on_dashboard(self):
        poll = Post.objects.create(author=self.cds, kind="POLL", text="Date de la formation P3 ?")
        o1 = PollOption.objects.create(post=poll, text="Jeudi", order=1)
        PollOption.objects.create(post=poll, text="Vendredi", order=2)
        self.client.force_login(self.cds)
        self.client.post(reverse("feed:feature", args=[poll.pk]))
        self.client.force_login(self.tl)
        dash = self.client.get(reverse("core:dashboard"))
        self.assertContains(dash, 'id="une-interactive"')
        self.assertContains(dash, f'data-option="{o1.pk}"')                   # on vote depuis « À la une »
        self.client.post(reverse("feed:vote", args=[poll.pk]), {"option": o1.pk})
        self.assertContains(self.client.get(reverse("core:dashboard")), "100 %")   # résultats après vote

        challenge = Post.objects.create(author=self.cds, kind="CHALLENGE", text="Bacille découvert en 1882 ?",
                                        answer="Koch", hint="Prix Nobel 1905")
        self.client.force_login(self.cds)
        self.client.post(reverse("feed:feature", args=[challenge.pk]))
        self.client.force_login(self.tl)
        dash = self.client.get(reverse("core:dashboard"))
        self.assertContains(dash, "hot-answer-form")
        self.assertContains(dash, "Prix Nobel 1905")
        self.assertNotContains(dash, "Koch")
        self.assertTrue(self.client.post(reverse("feed:answer", args=[challenge.pk]), {"text": "koch"}).json()["correct"])
        self.assertContains(self.client.get(reverse("core:dashboard")), "bravo, trouvé")
        # publication supprimée : le contenu reste, avec une mention
        challenge.delete()
        dash = self.client.get(reverse("core:dashboard"))
        self.assertContains(dash, "Bacille découvert en 1882")
        self.assertContains(dash, "la publication d'origine a été supprimée")
