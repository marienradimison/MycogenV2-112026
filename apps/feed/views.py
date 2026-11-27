from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import ChallengeAnswer, Comment, Highlight, PollOption, Post, Reaction, Vote, normalize

MAX_PHOTO = 5 * 1024 * 1024
FEED_SIZE = 15


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ["text", "photo", "priority", "kind", "answer", "hint"]

    def __init__(self, *args, options=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.options = [o.strip()[:150] for o in options or [] if o.strip()]

    def clean(self):
        data = super().clean()
        kind = data.get("kind") or "MESSAGE"
        if kind == "POLL" and len(self.options) < 2:
            raise forms.ValidationError("Un sondage doit proposer au moins 2 choix.")
        if kind == "CHALLENGE" and not normalize(data.get("answer")):
            raise forms.ValidationError("Indiquez la réponse attendue du challenge.")
        if kind != "CHALLENGE":
            data["answer"] = data["hint"] = ""
        return data

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "size") and photo.size > MAX_PHOTO:
            raise forms.ValidationError("Photo trop lourde (5 Mo maximum).")
        return photo


def posts_queryset(user):
    return (Post.objects.select_related("author", "author__profile")
            .prefetch_related(Prefetch("comments", queryset=Comment.objects.select_related("author", "author__profile")),
                              "reactions", "options", "votes",
                              Prefetch("answers", queryset=ChallengeAnswer.objects.select_related("user")))
            .annotate(n_comments=Count("comments", distinct=True))
            .order_by("-created_at"))  # Meta.ordering est ignoré avec annotate/GROUP BY


def decorate(posts, user):
    """Ajoute à chaque publication le décompte des réactions et la réaction de l'utilisateur."""
    emojis = dict(Reaction.KINDS)
    can_feature = user.has_perm("feed.manage_highlight")
    featured_id = Highlight.objects.filter(current=True).values_list("post_id", flat=True).first()
    for p in posts:
        counts = {}
        p.my_reaction = None
        for r in p.reactions.all():
            counts[r.kind] = counts.get(r.kind, 0) + 1
            if r.user_id == user.pk:
                p.my_reaction = r.kind
        p.reaction_bar = [(k, emojis[k], counts.get(k, 0)) for k, _ in Reaction.KINDS]
        p.n_reactions = sum(counts.values())
        p.can_delete = user.pk == p.author_id or user.is_staff
        p.is_author = user.pk == p.author_id
        p.can_feature = can_feature
        p.featured = p.pk == featured_id
        if p.kind == "POLL":
            votes = list(p.votes.all())
            p.n_votes = len(votes)
            p.my_vote = next((v.option_id for v in votes if v.user_id == user.pk), None)
            per = {}
            for v in votes:
                per[v.option_id] = per.get(v.option_id, 0) + 1
            p.poll = [{"option": o, "n": per.get(o.pk, 0),
                       "pct": round(100 * per.get(o.pk, 0) / len(votes)) if votes else 0} for o in p.options.all()]
            p.show_results = p.my_vote is not None or p.closed or p.is_author
        elif p.kind == "CHALLENGE":
            answers = list(p.answers.all())
            winners, seen = [], set()
            for a in answers:
                if a.correct and a.user_id not in seen:
                    seen.add(a.user_id)
                    winners.append(a)
            p.winners = winners
            p.solved = user.pk in seen
            p.tries = sum(1 for a in answers if a.user_id == user.pk)
            p.show_answer = p.revealed or p.solved or p.is_author
    return posts


@login_required
def feed(request):
    """Fragment HTML des publications (rafraîchi en JavaScript après chaque action)."""
    page = Paginator(posts_queryset(request.user), FEED_SIZE).get_page(request.GET.get("page"))
    return render(request, "feed/_posts.html", {"posts": decorate(page.object_list, request.user)})


@login_required
def state(request):
    """Interrogé toutes les 20 s par le tableau de bord pour détecter les nouvelles publications."""
    last = Post.objects.values("id", "author_id").first()
    return JsonResponse({"latest": last["id"] if last else 0,
                         "mine": bool(last and last["author_id"] == request.user.pk)})


@login_required
@require_POST
def create(request):
    data = request.POST.copy()
    data.setdefault("priority", "NORMAL")
    data.setdefault("kind", "MESSAGE")
    form = PostForm(data, request.FILES, options=request.POST.getlist("option"))
    if form.is_valid():
        post = form.save(commit=False)
        post.author = request.user
        post.save()
        if post.kind == "POLL":
            PollOption.objects.bulk_create(PollOption(post=post, text=t, order=i) for i, t in enumerate(form.options[:10]))
        return JsonResponse({"ok": True, "id": post.pk})
    errors = " ".join(e for errs in form.errors.values() for e in errs)
    return JsonResponse({"ok": False, "error": errors}, status=400)


@login_required
@require_POST
def delete(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if post.author_id != request.user.pk and not request.user.is_staff:
        raise PermissionDenied
    post.photo.delete(save=False)
    post.delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def react(request, pk):
    post = get_object_or_404(Post, pk=pk)
    kind = request.POST.get("kind")
    if kind not in dict(Reaction.KINDS):
        return JsonResponse({"ok": False}, status=400)
    existing = Reaction.objects.filter(post=post, user=request.user).first()
    if existing and existing.kind == kind:
        existing.delete()  # re-cliquer retire la réaction
    else:
        Reaction.objects.update_or_create(post=post, user=request.user, defaults={"kind": kind})
    return JsonResponse({"ok": True})


@login_required
@require_POST
def comment(request, pk):
    post = get_object_or_404(Post, pk=pk)
    text = request.POST.get("text", "").strip()[:1000]
    if text:
        Comment.objects.create(post=post, author=request.user, text=text)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def comment_delete(request, pk):
    c = get_object_or_404(Comment, pk=pk)
    if c.author_id != request.user.pk and not request.user.is_staff:
        raise PermissionDenied
    c.delete()
    return JsonResponse({"ok": True})


@login_required
def archive(request):
    page = Paginator(Post.objects.all(), FEED_SIZE).get_page(request.GET.get("page"))
    return render(request, "feed/archive.html", {"page_obj": page})


@login_required
@require_POST
def vote(request, pk):
    post = get_object_or_404(Post, pk=pk, kind="POLL")
    if not (request.POST.get("option") or "").isdigit():
        return JsonResponse({"ok": False}, status=400)
    option = get_object_or_404(PollOption, pk=request.POST["option"], post=post)
    if post.closed:
        return JsonResponse({"ok": False, "error": "Sondage clôturé."}, status=400)
    Vote.objects.update_or_create(post=post, user=request.user, defaults={"option": option})
    return JsonResponse({"ok": True})


@login_required
@require_POST
def answer(request, pk):
    post = get_object_or_404(Post, pk=pk, kind="CHALLENGE")
    text = request.POST.get("text", "").strip()[:200]
    if post.closed or post.revealed:
        return JsonResponse({"ok": False, "error": "Challenge terminé."}, status=400)
    if post.author_id == request.user.pk:
        return JsonResponse({"ok": False, "error": "Vous êtes l'auteur de ce challenge."}, status=400)
    if not text:
        return JsonResponse({"ok": False}, status=400)
    if post.answers.filter(user=request.user, correct=True).exists():
        return JsonResponse({"ok": True, "correct": True})
    correct = normalize(text) == normalize(post.answer)
    ChallengeAnswer.objects.create(post=post, user=request.user, text=text, correct=correct)
    return JsonResponse({"ok": True, "correct": correct})


@login_required
@require_POST
def close(request, pk):
    """Auteur : clôturer un sondage, ou dévoiler la réponse d'un challenge."""
    post = get_object_or_404(Post, pk=pk)
    if post.author_id != request.user.pk and not request.user.is_staff:
        raise PermissionDenied
    post.closed = True
    post.revealed = post.kind == "CHALLENGE"
    post.save(update_fields=["closed", "revealed"])
    return JsonResponse({"ok": True})

# ---------------------------------------------------------------- À la une (tableau de bord)

class HighlightForm(forms.ModelForm):
    remove_image = forms.BooleanField(label="Retirer l'image", required=False)

    class Meta:
        model = Highlight
        fields = ["title", "text", "image", "link"]
        widgets = {"text": forms.Textarea(attrs={"rows": 7})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            css = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            field.widget.attrs.setdefault("class", css)

    def clean_link(self):
        link = (self.cleaned_data.get("link") or "").strip()
        if link and not link.startswith(("/", "http://", "https://")):
            raise forms.ValidationError("Indiquez une adresse commençant par / (page de MYCOGEN) ou par https://.")
        return link

    def clean(self):
        data = super().clean()
        has_image = data.get("image") or (self.instance.image and not data.get("remove_image"))
        if not (data.get("title") or data.get("text") or has_image):
            raise forms.ValidationError("Saisissez au moins un titre, un texte ou une image.")
        return data

    def save(self, commit=True):
        if self.cleaned_data.get("remove_image") and self.instance.image and not self.cleaned_data.get("image"):
            self.instance.image.delete(save=False)
            self.instance.image = ""
        return super().save(commit)


@login_required
@permission_required("feed.manage_highlight", raise_exception=True)
@require_POST
def feature(request, pk):
    """Met une publication à la une (copie modifiable de son texte et de sa photo)."""
    post = get_object_or_404(Post, pk=pk)
    Highlight.from_post(post, request.user)
    return JsonResponse({"ok": True, "reload_page": True})


@login_required
@permission_required("feed.manage_highlight", raise_exception=True)
def highlight_edit(request, pk=None):
    """Modifier la « À la une » (pk), ou en créer une nouvelle (sans pk) ; historique des précédentes."""
    instance = get_object_or_404(Highlight, pk=pk) if pk else None
    form = HighlightForm(request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        h = form.save(commit=False)
        h.updated_by = request.user
        if not h.pk:
            h.created_by = request.user
        h.save()
        if not pk or request.POST.get("show") == "1":
            h.make_current(request.user)
        messages.success(request, "« À la une » enregistrée.")
        return redirect("core:dashboard")
    return render(request, "feed/highlight_form.html", {
        "form": form, "highlight": instance,
        "history": Highlight.objects.select_related("post", "created_by", "updated_by")[:30],
    })


@login_required
@permission_required("feed.manage_highlight", raise_exception=True)
@require_POST
def highlight_state(request, pk):
    """Remettre une ancienne « À la une » en avant, la retirer du tableau de bord, ou la supprimer."""
    h = get_object_or_404(Highlight, pk=pk)
    action = request.POST.get("action")
    if action == "show":
        h.make_current(request.user)
        messages.success(request, "Remise à la une.")
    elif action == "hide":
        h.current = False
        h.save(update_fields=["current"])
        messages.success(request, "Retirée du tableau de bord.")
    elif action == "delete":
        if h.image:
            h.image.delete(save=False)
        h.delete()
        messages.success(request, "Supprimée.")
    return redirect("feed:highlight_new")
