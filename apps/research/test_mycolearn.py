import shutil
import tempfile

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CollectionItem, LearningActivity, LearningCollection, LearningDomain, LearningResource

MEDIA = tempfile.mkdtemp(prefix="mycogen-test-media-")


@override_settings(MEDIA_ROOT=MEDIA)
class MediathequeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("init_mycogen", verbosity=0)
        cls.al = User.objects.create_user("agent", password="x")
        cls.al.groups.add(Group.objects.get(role_code__code="AL"))
        cls.rsr = User.objects.create_user("chercheur", password="x")
        cls.rsr.groups.add(Group.objects.get(role_code__code="RSR"))
        cls.bio = LearningDomain.objects.get(name="Bioinformatique")
        cls.video = LearningResource.objects.create(
            title="Introduction à TB-Profiler", domain=cls.bio, kind="VIDEO", featured=True, tags="WGS, résistance",
            file=SimpleUploadedFile("intro.mp4", bytes(range(256)) * 40))
        cls.yt = LearningResource.objects.create(title="Cours en ligne", domain=cls.bio, kind="VIDEO",
                                                 url="https://youtu.be/dQw4w9WgXcQ", language="EN")
        cls.hidden = LearningResource.objects.create(title="Brouillon caché", domain=cls.bio, kind="LINK",
                                                     url="https://example.org", published=False)
        cls.course = LearningCollection.objects.create(title="Initiation bioinformatique", domain=cls.bio)
        CollectionItem.objects.create(collection=cls.course, resource=cls.video, order=1)
        CollectionItem.objects.create(collection=cls.course, resource=cls.yt, order=2)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def test_home_rows_and_search(self):
        self.client.force_login(self.al)
        home = self.client.get(reverse("research:mycolearn"))
        for text in ("À la une", "Introduction à TB-Profiler", "Nouveautés", "Collections et parcours",
                     "Initiation bioinformatique", "i.ytimg.com/vi/dQw4w9WgXcQ"):
            self.assertContains(home, text)
        self.assertNotContains(home, "Brouillon caché")
        self.assertNotContains(home, "Ajouter un support")                    # AL : consultation seulement
        found = self.client.get(reverse("research:mycolearn"), {"tag": "résistance"})
        self.assertContains(found, "Introduction à TB-Profiler")
        self.assertNotContains(found, "Cours en ligne")
        self.assertContains(self.client.get(reverse("research:mycolearn"), {"langue": "EN"}), "Cours en ligne")
        self.client.force_login(self.rsr)
        self.assertContains(self.client.get(reverse("research:mycolearn"), {"q": "Brouillon"}), "Brouillon caché")

    def test_player_progress_resume_and_collection(self):
        self.client.force_login(self.al)
        url = f"{self.video.get_absolute_url()}?collection={self.course.pk}"
        page = self.client.get(url)
        self.assertContains(page, "<video")
        self.assertContains(page, "Suivant : Cours en ligne")
        self.video.refresh_from_db()
        self.assertEqual(self.video.view_count, 1)
        self.client.get(url)                                                   # même utilisateur < 30 min
        self.video.refresh_from_db()
        self.assertEqual(self.video.view_count, 1)
        prog = reverse("research:learning_progress", args=[self.video.pk])
        self.assertEqual(self.client.post(prog, {"position": "30", "duration": "120"}).json()["percent"], 25)
        home = self.client.get(reverse("research:mycolearn"))
        self.assertContains(home, "Continuer")
        self.assertContains(self.client.get(url), "resumeAt = 30.0")
        self.assertTrue(self.client.post(prog, {"position": "110", "duration": "120"}).json()["completed"])
        self.video.refresh_from_db()
        self.assertEqual(self.video.duration_min, 2)                           # durée déduite du fichier
        page = self.client.get(self.course.get_absolute_url())
        self.assertContains(page, "1 / 2 terminé")
        # YouTube intégré
        self.assertContains(self.client.get(self.yt.get_absolute_url()), "youtube-nocookie.com/embed/dQw4w9WgXcQ")
        # support non publié : introuvable pour AL
        self.assertEqual(self.client.post(reverse("research:learning_progress", args=[self.hidden.pk]),
                                          {"position": "1"}).status_code, 404)

    def test_my_list(self):
        self.client.force_login(self.al)
        self.client.post(reverse("research:learning_favorite", args=[self.yt.pk]))
        self.assertTrue(LearningActivity.objects.get(user=self.al, resource=self.yt).favorite)
        mylist = self.client.get(reverse("research:mycolearn"), {"liste": "favoris"})
        self.assertContains(mylist, "Cours en ligne")
        self.assertNotContains(mylist, "Introduction à TB-Profiler")
        r = self.client.post(reverse("research:learning_favorite", args=[self.yt.pk]), HTTP_X_REQUESTED_WITH="fetch")
        self.assertFalse(r.json()["favorite"])

    def test_video_streaming_with_range(self):
        self.client.force_login(self.al)
        url = self.video.file.url
        r = self.client.get(url, HTTP_RANGE="bytes=100-199")
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r["Content-Range"], f"bytes 100-199/{self.video.file.size}")
        self.assertEqual(b"".join(r.streaming_content), (bytes(range(256)) * 40)[100:200])
        self.assertEqual(self.client.get(url, HTTP_RANGE="bytes=999999-").status_code, 416)
        self.assertEqual(self.client.get(url).status_code, 200)
