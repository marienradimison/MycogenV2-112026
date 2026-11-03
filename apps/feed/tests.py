from datetime import date
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from . import news
from .models import Comment, NewsArticle, Post, Reaction


class HotFeedTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password="x", first_name="Alice")
        self.bob = User.objects.create_user("bob", password="x")
        self.client.force_login(self.alice)

    def test_publish_react_comment(self):
        r = self.client.post(reverse("feed:create"), {"text": "Coupure d'électricité salle P3 !", "priority": "URGENT"})
        self.assertEqual(r.json()["ok"], True)
        post = Post.objects.get()
        self.assertEqual((post.author, post.priority), (self.alice, "URGENT"))
        self.client.post(reverse("feed:create"), {"text": "Info normale"})
        self.assertEqual(Post.objects.filter(priority="NORMAL").count(), 1)

        self.client.post(reverse("feed:react", args=[post.pk]), {"kind": "fire"})
        self.client.post(reverse("feed:react", args=[post.pk]), {"kind": "like"})  # change de réaction
        self.assertEqual(Reaction.objects.get().kind, "like")
        self.client.post(reverse("feed:react", args=[post.pk]), {"kind": "like"})  # re-clic = retrait
        self.assertFalse(Reaction.objects.exists())

        self.client.post(reverse("feed:comment", args=[post.pk]), {"text": "Groupe électrogène lancé"})
        self.assertEqual(Comment.objects.get().author, self.alice)
        html = self.client.get(reverse("feed:feed")).content.decode()
        self.assertIn("Coupure", html)
        self.assertLess(html.index("Info normale"), html.index("Coupure"))  # plus récente en premier
        self.assertIn("Groupe électrogène", html)
        self.assertEqual(self.client.get(reverse("feed:state")).json(), {"latest": Post.objects.first().pk, "mine": True})

    def test_only_author_or_staff_can_delete(self):
        post = Post.objects.create(author=self.bob, text="à moi")
        self.assertEqual(self.client.post(reverse("feed:delete", args=[post.pk])).status_code, 403)
        self.client.force_login(self.bob)
        self.client.post(reverse("feed:delete", args=[post.pk]))
        self.assertFalse(Post.objects.exists())

    def test_empty_post_rejected(self):
        r = self.client.post(reverse("feed:create"), {"text": ""})
        self.assertEqual(r.status_code, 400)

    def test_poll(self):
        r = self.client.post(reverse("feed:create"), {"kind": "POLL", "text": "Date du pot de fin d'année ?",
                                                       "option": ["Vendredi 18", "Samedi 19", ""]})
        self.assertTrue(r.json()["ok"])
        post = Post.objects.get(kind="POLL")
        self.assertEqual([o.text for o in post.options.all()], ["Vendredi 18", "Samedi 19"])
        bad = self.client.post(reverse("feed:create"), {"kind": "POLL", "text": "?", "option": ["Seul choix"]})
        self.assertContains(bad, "au moins 2 choix", status_code=400)
        # Bob vote (résultats masqués avant son vote), change d'avis ; un seul vote par personne
        self.client.force_login(self.bob)
        html = self.client.get(reverse("feed:feed")).content.decode()
        self.assertNotIn("%</span>", html)
        o1, o2 = post.options.all()
        self.client.post(reverse("feed:vote", args=[post.pk]), {"option": o1.pk})
        self.client.post(reverse("feed:vote", args=[post.pk]), {"option": o2.pk})
        self.assertEqual(list(post.votes.values_list("option", flat=True)), [o2.pk])
        self.assertIn("100 %", self.client.get(reverse("feed:feed")).content.decode())
        # clôture réservée à l'auteure
        self.assertEqual(self.client.post(reverse("feed:close", args=[post.pk])).status_code, 403)
        self.client.force_login(self.alice)
        self.client.post(reverse("feed:close", args=[post.pk]))
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(reverse("feed:vote", args=[post.pk]), {"option": o1.pk}).status_code, 400)

    def test_challenge(self):
        r = self.client.post(reverse("feed:create"), {"kind": "CHALLENGE", "text": "Bacille acido-alcoolo… ?",
                                                       "answer": "Résistant", "hint": "R…"})
        self.assertTrue(r.json()["ok"])
        post = Post.objects.get(kind="CHALLENGE")
        bad = self.client.post(reverse("feed:create"), {"kind": "CHALLENGE", "text": "x"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("réponse attendue", bad.json()["error"])
        self.client.force_login(self.bob)
        html = self.client.get(reverse("feed:feed")).content.decode()
        self.assertNotIn("Résistant", html)                             # réponse cachée
        self.assertIn("Indice : R…", html)
        self.assertFalse(self.client.post(reverse("feed:answer", args=[post.pk]), {"text": "sensible"}).json()["correct"])
        self.assertTrue(self.client.post(reverse("feed:answer", args=[post.pk]), {"text": "  RESISTANT !"}).json()["correct"])
        html = self.client.get(reverse("feed:feed")).content.decode()
        self.assertIn("bravo, trouvé", html)
        self.assertIn("🥇", html)
        self.client.force_login(self.alice)
        self.client.post(reverse("feed:close", args=[post.pk]))
        post.refresh_from_db()
        self.assertTrue(post.revealed)

    def test_dashboard_and_archive_render(self):
        Post.objects.create(author=self.bob, text="test")
        self.alice.is_superuser = True
        self.alice.save()
        self.assertContains(self.client.get(reverse("core:dashboard")), "Chaud Chaud Chaud")
        self.assertEqual(self.client.get(reverse("feed:archive")).status_code, 200)


class NewsTests(TestCase):
    def fake(self, source, n, rank=0):
        return [{"source": source, "external_id": f"{source}:{i}", "title": f"{source} {i}", "url": "https://x.org",
                 "publisher": "P", "published": date.today(), "summary": "", "rank": rank} for i in range(n)]

    def test_weekly_selection_two_papers_one_news(self):
        with mock.patch.object(news, "fetch_pubmed", return_value=self.fake("PUBMED", 5)), \
             mock.patch.object(news, "fetch_rss", side_effect=lambda s, u, k: self.fake(s, 2)):
            self.assertEqual(news.refresh(), 3)
            self.assertEqual(news.refresh(), 0)  # semaine déjà complète
        sources = sorted(NewsArticle.objects.values_list("source", flat=True))
        self.assertEqual(sources, ["PUBMED", "PUBMED", "WHO"])
        self.assertEqual(len(news.current_articles()), 3)

    def test_fallback_when_pubmed_down(self):
        with mock.patch.object(news, "fetch_pubmed", side_effect=OSError("hors ligne")), \
             mock.patch.object(news, "fetch_rss", side_effect=lambda s, u, k: self.fake(s, 1)):
            self.assertEqual(news.refresh(), 3)

    def test_trusted_press(self):
        self.assertTrue(news.trusted("Le Monde.fr"))
        self.assertTrue(news.trusted("Midi Madagasikara"))
        self.assertTrue(news.trusted("Reuters"))
        self.assertFalse(news.trusted("Epoch Times"))
        self.assertFalse(news.trusted("Santé Nature Innovation"))

    def test_journal_rank(self):
        self.assertLess(news.journal_rank("The Lancet. Infectious diseases"), news.journal_rank("Obscure J"))
        self.assertEqual(news.journal_rank("The Lancet. Infectious diseases"),
                         news.TOP_JOURNALS.index("lancet infectious diseases"))
        self.assertEqual(news.journal_rank("The Lancet"), news.TOP_JOURNALS.index("lancet"))
