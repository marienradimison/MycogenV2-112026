from django import forms
from django.db import models


def lims_formfield(field, **kwargs):
    """Widgets HTML5 pour les dates (utilisé par modelform_factory)."""
    if isinstance(field, models.DateTimeField):
        kwargs.setdefault("widget", forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"))
    elif isinstance(field, models.DateField):
        kwargs.setdefault("widget", forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    elif isinstance(field, models.TextField):
        kwargs.setdefault("widget", forms.Textarea(attrs={"rows": 3}))
    return field.formfield(**kwargs)


class BootstrapFormMixin:
    """Ajoute les classes Bootstrap 5 à tous les widgets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, (forms.CheckboxInput,)):
                w.attrs["class"] = "form-check-input"
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs["class"] = "form-select"
            else:
                w.attrs["class"] = "form-control"
            if isinstance(w, forms.ClearableFileInput):
                w.attrs["class"] = "form-control"


class LimsModelForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        formfield_callback = lims_formfield
