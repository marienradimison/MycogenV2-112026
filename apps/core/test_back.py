"""Bouton « Préc. » : page parente logique, jamais une page supprimée."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.feed.models import Highlight


def back_href(html):
    i = html.index("back-btn")
    start = html.index('href="', i) + 6
    return html[start:html.index('"', start)]


class BackButtonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("adm", "a@example.org", "x")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_logical_parents(self):
        from apps.core.models import Room
        room = Room.objects.create(number="T01", name="Salle test")
        # fiche → liste ; modification → fiche ; création → liste
        self.assertEqual(back_href(self.client.get(room.get_absolute_url()).content.decode()), reverse("core:room_list"))
        self.assertEqual(back_href(self.client.get(reverse("core:room_update", args=[room.pk])).content.decode()),
                         room.get_absolute_url())
        self.assertEqual(back_href(self.client.get(reverse("core:room_create")).content.decode()), reverse("core:room_list"))
        # « À la une » → tableau de bord (même après suppression d'une « À la une »)
        h = Highlight.objects.create(title="Temporaire")
        self.client.post(reverse("feed:highlight_state", args=[h.pk]), {"action": "delete"})
        page = self.client.get(reverse("feed:highlight_new")).content.decode()
        self.assertEqual(back_href(page), "/")
        # sous-modules → module / sous-module parent
        self.assertEqual(back_href(self.client.get(reverse("quality:sgq")).content.decode()),
                         reverse("core:module", args=["quality"]))
        self.assertEqual(back_href(self.client.get(reverse("quality:monitoring")).content.decode()),
                         reverse("quality:equipment_list"))
        self.assertEqual(back_href(self.client.get(reverse("research:mycolearn")).content.decode()),
                         reverse("core:module", args=["research"]))

    def test_child_record_returns_to_parent_and_next_is_honoured(self):
        from apps.research.models import LabNotebook, NotebookEntry
        nb = LabNotebook.objects.create(code="CL-1", title="Cahier")
        entry = NotebookEntry.objects.create(notebook=nb, title="Entrée")
        self.assertEqual(back_href(self.client.get(entry.get_absolute_url()).content.decode()), nb.get_absolute_url())
        url = reverse("research:entry_create") + f"?notebook={nb.pk}&next={nb.get_absolute_url()}"
        self.assertEqual(back_href(self.client.get(url).content.decode()), nb.get_absolute_url())
        evil = reverse("research:entry_create") + "?next=https://example.com/"
        self.assertEqual(back_href(self.client.get(evil).content.decode()), reverse("research:entry_list"))

    def test_no_history_stack_left(self):
        js = (self.client.get("/static/js/nav.js").content.decode() if False else
              open("static/js/nav.js", encoding="utf-8").read())
        self.assertNotIn("stack", js)
