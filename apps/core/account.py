"""Paramètres utilisateur (profil, thème, sécurité, signalement de bug) et support administrateur."""
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .crud import safe_next
from .forms import BootstrapFormMixin
from .models import BugReport, PasswordResetRequest, UserProfile

MAX_PHOTO = 2 * 1024 * 1024
SECTIONS = ["profil", "apparence", "securite", "bug"]


def get_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


class UserForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "email"]


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    remove_photo = forms.BooleanField(label="Supprimer la photo", required=False)

    class Meta:
        model = UserProfile
        fields = ["job_title", "phone", "photo"]
        widgets = {"photo": forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp"})}

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "size") and photo.size > MAX_PHOTO:
            raise forms.ValidationError("Image trop lourde (2 Mo maximum).")
        return photo


class ThemeForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["theme"]
        widgets = {"theme": forms.RadioSelect}


class BugForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BugReport
        fields = ["title", "severity", "page", "description", "screenshot"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5}),
                   "screenshot": forms.FileInput(attrs={"accept": "image/*"})}


class PasswordForm(BootstrapFormMixin, PasswordChangeForm):
    pass


@login_required
def settings_view(request, section="profil"):
    if section not in SECTIONS:
        section = "profil"
    profile = get_profile(request.user)
    user_form = UserForm(instance=request.user)
    profile_form = ProfileForm(instance=profile)
    theme_form = ThemeForm(instance=profile)
    password_form = PasswordForm(request.user)
    bug_form = BugForm(initial={"page": request.GET.get("page", "")})

    if request.method == "POST":
        if section == "profil":
            user_form = UserForm(request.POST, instance=request.user)
            profile_form = ProfileForm(request.POST, request.FILES, instance=profile)
            if user_form.is_valid() and profile_form.is_valid():
                user_form.save()
                p = profile_form.save(commit=False)
                if profile_form.cleaned_data.get("remove_photo"):
                    p.photo.delete(save=False)
                    p.photo = ""
                p.save()
                messages.success(request, "Profil mis à jour.")
                return redirect("core:settings", section="profil")
        elif section == "apparence":
            theme_form = ThemeForm(request.POST, instance=profile)
            if theme_form.is_valid():
                theme_form.save()
                messages.success(request, "Thème enregistré.")
                return redirect("core:settings", section="apparence")
        elif section == "securite":
            if request.POST.get("action") == "reset_request":
                PasswordResetRequest.objects.create(username=request.user.username, user=request.user,
                                                    message="Demande depuis les paramètres du compte")
                messages.info(request, "Demande transmise à l'administrateur.")
                return redirect("core:settings", section="securite")
            password_form = PasswordForm(request.user, request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, "Mot de passe modifié.")
                return redirect("core:settings", section="securite")
        elif section == "bug":
            bug_form = BugForm(request.POST, request.FILES)
            if bug_form.is_valid():
                bug = bug_form.save(commit=False)
                bug.reporter = request.user
                bug.save()
                messages.success(request, f"Merci ! Problème #{bug.pk} transmis à l'administrateur.")
                return redirect("core:settings", section="bug")

    return render(request, "core/settings.html", {
        "section": section, "profile": profile, "user_form": user_form, "profile_form": profile_form,
        "theme_form": theme_form, "password_form": password_form, "bug_form": bug_form,
        "my_bugs": request.user.bug_reports.all()[:20],
        "my_resets": request.user.reset_requests.filter(status="OPEN").exists(),
    })


@login_required
@require_POST
def toggle_theme(request):
    profile = get_profile(request.user)
    profile.theme = "light" if request.POST.get("current") == "dark" else "dark"
    profile.save(update_fields=["theme"])
    return redirect(safe_next(request, request.POST.get("next"), "/"))


class ResetRequestForm(BootstrapFormMixin, forms.Form):
    username = forms.CharField(label="Identifiant", max_length=150)
    message = forms.CharField(label="Message (facultatif)", max_length=255, required=False,
                              widget=forms.TextInput(attrs={"placeholder": "Ex. poste, service, téléphone"}))


def reset_request(request):
    """Mot de passe oublié : la demande est traitée par un administrateur (pas d'e-mail en intranet)."""
    form = ResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"].strip()
        user = get_user_model().objects.filter(username__iexact=username).first()
        PasswordResetRequest.objects.create(username=username, user=user, message=form.cleaned_data["message"])
        # Réponse identique que le compte existe ou non (pas d'énumération des comptes)
        return render(request, "registration/reset_request.html", {"sent": True})
    return render(request, "registration/reset_request.html", {"form": form})


def is_staff(user):
    return user.is_active and user.is_staff


@login_required
@user_passes_test(is_staff)
def support(request):
    return render(request, "core/support.html", {
        "resets": PasswordResetRequest.objects.select_related("user", "handled_by")[:100],
        "bugs": BugReport.objects.select_related("reporter")[:100],
        "bug_statuses": BugReport.STATUS,
    })


@login_required
@user_passes_test(is_staff)
@require_POST
def support_action(request, kind, pk):
    if kind == "reset":
        obj = get_object_or_404(PasswordResetRequest, pk=pk)
        status = request.POST.get("status", "DONE")
        obj.status = status if status in dict(PasswordResetRequest.STATUS) else "DONE"
        obj.handled_by, obj.handled_at = request.user, timezone.now()
        obj.save()
    else:
        obj = get_object_or_404(BugReport, pk=pk)
        status = request.POST.get("status", obj.status)
        obj.status = status if status in dict(BugReport.STATUS) else obj.status
        obj.response = request.POST.get("response", obj.response)
        obj.save()
    messages.success(request, "Mis à jour.")
    return redirect("core:support")
