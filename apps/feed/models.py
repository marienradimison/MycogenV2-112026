import re
import unicodedata

from django.conf import settings
from django.db import models


def normalize(text):
    """Comparaison souple des réponses : sans accents, casse, ponctuation ni espaces multiples."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


class Post(models.Model):
    """Publication « Chaud Chaud Chaud!!! » : information urgente partagée avec l'unité."""

    PRIORITY = [("NORMAL", "Info"), ("URGENT", "Urgent")]
    KINDS = [("MESSAGE", "Message"), ("POLL", "Sondage"), ("CHALLENGE", "Challenge")]

    author = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="auteur", on_delete=models.CASCADE,
                               related_name="posts")
    created_at = models.DateTimeField("publié le", auto_now_add=True)
    text = models.TextField("message", max_length=3000)
    photo = models.ImageField("photo", upload_to="feed/%Y/%m/", blank=True)
    priority = models.CharField("priorité", max_length=6, choices=PRIORITY, default="NORMAL")
    kind = models.CharField("type", max_length=9, choices=KINDS, default="MESSAGE")
    # Challenge (jeu de mots, devinette…) : réponse attendue, indice, réponse dévoilée par l'auteur
    answer = models.CharField("réponse attendue", max_length=200, blank=True)
    hint = models.CharField("indice", max_length=200, blank=True)
    revealed = models.BooleanField("réponse dévoilée", default=False)
    closed = models.BooleanField("clôturé", default=False, help_text="Sondage / challenge : plus de vote ni de réponse")

    class Meta:
        verbose_name = "publication"
        verbose_name_plural = "publications"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.author} · {self.text[:40]}"


class PollOption(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="options")
    text = models.CharField("choix", max_length=150)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "choix de sondage"
        ordering = ["order", "id"]

    def __str__(self):
        return self.text


class Vote(models.Model):
    """Vote anonyme (seuls les totaux sont affichés) ; un vote par personne, modifiable."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="votes")
    option = models.ForeignKey(PollOption, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")

    class Meta:
        verbose_name = "vote"
        unique_together = [("post", "user")]


class ChallengeAnswer(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="answers")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    text = models.CharField("réponse", max_length=200)
    correct = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "réponse au challenge"
        ordering = ["created_at"]


class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="auteur", on_delete=models.CASCADE,
                               related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    text = models.TextField("commentaire", max_length=1000)

    class Meta:
        verbose_name = "commentaire"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.author} → #{self.post_id}"


class Reaction(models.Model):
    KINDS = [("like", "👍"), ("love", "❤️"), ("fire", "🔥"), ("wow", "😮"), ("sad", "😢")]

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=5, choices=KINDS)

    class Meta:
        verbose_name = "réaction"
        unique_together = [("post", "user")]


class NewsArticle(models.Model):
    """Actualité scientifique sélectionnée automatiquement (3 par semaine)."""

    SOURCES = [("PUBMED", "PubMed"), ("WHO", "OMS"), ("SCIENCEDAILY", "ScienceDaily"),
               ("GNEWS", "Google Actualités")]

    source = models.CharField("source", max_length=12, choices=SOURCES)
    external_id = models.CharField(max_length=300, unique=True)
    title = models.CharField("titre", max_length=500)
    url = models.URLField("lien", max_length=1000)
    publisher = models.CharField("revue / éditeur", max_length=255, blank=True)
    published = models.DateField("date de publication", null=True, blank=True)
    summary = models.TextField("résumé", blank=True)
    week = models.DateField("semaine (lundi)", db_index=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "actualité scientifique"
        verbose_name_plural = "actualités scientifiques"
        ordering = ["-week", "id"]

    def __str__(self):
        return self.title


class Highlight(models.Model):
    """« À la une » du tableau de bord : contenu mis en avant, créé à partir d'une publication de Chaud Chaud Chaud!!!
    ou saisi directement, et modifiable à tout moment. Une seule « À la une » est affichée (current)."""

    title = models.CharField("titre", max_length=150, blank=True)
    text = models.TextField("texte", max_length=3000, blank=True)
    image = models.ImageField("image", upload_to="feed/une/%Y/", blank=True)
    link = models.CharField("lien", max_length=300, blank=True,
                            help_text="Facultatif : adresse d'une page (ex. /recherche/mycolearn/ ou https://…)")
    post = models.ForeignKey(Post, verbose_name="publication d'origine", on_delete=models.SET_NULL, null=True,
                             blank=True, related_name="highlights", editable=False)
    post_kind = models.CharField("type de la publication", max_length=9, choices=Post.KINDS, blank=True,
                                 editable=False)
    current = models.BooleanField("affichée à la une", default=False, editable=False)
    created_at = models.DateTimeField("créée le", auto_now_add=True)
    updated_at = models.DateTimeField("modifiée le", auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="mise à la une par", on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+", editable=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="modifiée par", on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+", editable=False)

    class Meta:
        verbose_name = "à la une"
        verbose_name_plural = "à la une"
        ordering = ["-current", "-updated_at"]
        permissions = [("manage_highlight", "Gérer « À la une » du tableau de bord")]

    def __str__(self):
        return self.title or (self.text[:60] if self.text else f"À la une n°{self.pk}")

    def make_current(self, user=None):
        Highlight.objects.filter(current=True).exclude(pk=self.pk).update(current=False)
        self.current = True
        if user is not None:
            self.updated_by = user
        self.save()

    @classmethod
    def from_post(cls, post, user):
        """Copie le texte et la photo de la publication (la « À la une » reste modifiable et survit à la publication)."""
        from django.core.files.base import ContentFile

        h = cls(text=post.text, post=post, post_kind=post.kind, created_by=user, updated_by=user)
        if post.photo:
            try:
                with post.photo.open("rb") as f:
                    h.image.save(post.photo.name.rsplit("/", 1)[-1], ContentFile(f.read()), save=False)
            except OSError:   # fichier de la photo absent
                pass
        h.make_current(user)
        return h

    @property
    def kind_label(self):
        """« Sondage » / « Challenge » si la « À la une » vient d'une publication interactive."""
        return {"POLL": "Sondage", "CHALLENGE": "Challenge"}.get(self.post_kind, "")

    @property
    def is_external(self):
        return self.link.startswith(("http://", "https://"))
