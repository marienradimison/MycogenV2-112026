"""Moteur CRUD générique du LIMS.

Chaque module déclare ses objets avec `Crud(...)` ; on obtient liste (recherche,
filtres, pagination, export CSV), fiche détaillée (avec objets liés), création,
modification, suppression et validation des résultats, avec permissions Django
et journal d'audit.
"""
import csv
from urllib.parse import urlencode
from functools import reduce
import operator

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import FieldDoesNotExist, PermissionDenied, ValidationError
from django.db.models import ProtectedError, Q
from django.forms import modelform_factory
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import capfirst
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import LimsModelForm, lims_formfield
from .models import ActivityLog

REGISTRY = {}


def safe_next(request, url, fallback):
    """URL de retour (`next`) limitée au site lui-même (pas de redirection vers un site externe)."""
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
        return url
    return fallback


def filter_or_ignore(qs, **lookup):
    """Filtre issu de l'URL : une valeur invalide (ex. ?project=abc) est ignorée au lieu de provoquer une erreur 500."""
    try:
        return qs.filter(**lookup)  # la conversion des valeurs (int, date…) a lieu ici
    except (ValueError, TypeError, ValidationError):
        return qs


def resolve(obj, name):
    """Résout `a__b__c` sur un objet."""
    for part in name.split("__"):
        if obj is None:
            return None
        obj = getattr(obj, part, None)
    if hasattr(obj, "all") and hasattr(obj, "model"):  # relation multiple (ManyToMany)
        return ", ".join(str(o) for o in obj.all())
    return obj() if callable(obj) and not hasattr(obj, "_meta") else obj


def field_label(model, name):
    try:
        parts = name.split("__")
        m = model
        for p in parts[:-1]:
            m = m._meta.get_field(p).related_model
        return capfirst(m._meta.get_field(parts[-1]).verbose_name)
    except (FieldDoesNotExist, AttributeError):
        return name.replace("_", " ").capitalize()


def log(user, action, obj, changes=None):
    ActivityLog.objects.create(
        user=user if user and user.is_authenticated else None,
        action=action,
        model=obj._meta.verbose_name,
        object_id=str(obj.pk),
        object_repr=str(obj)[:255],
        changes=changes or {},
    )


class Crud:
    def __init__(self, model, prefix, *, fields, list_display, search_fields=(), list_filter=(),
                 form_class=None, title=None, icon="bi-table", detail_template=None,
                 form_template=None, ordering=None, group=None, extra_context=None, exclude_urls=(), create_url=None, update_url=None, exporter=None,
                 date_filters=(), hidden_filters=(), list_title=None,
                 header_links=(), list_tabs=None):
        self.model = model
        self.prefix = prefix
        self.fields = fields
        self.list_display = list_display
        self.search_fields = search_fields
        self.list_filter = list_filter
        self.form_class = form_class
        self.title = title or capfirst(model._meta.verbose_name_plural)
        self.icon = icon
        self.detail_template = detail_template
        self.form_template = form_template
        self.ordering = ordering
        self.group = group
        self.extra_context = extra_context
        self.exporter = exporter  # export CSV spécifique : exporter(queryset) -> HttpResponse
        self.date_filters = date_filters      # filtres par date (champ de saisie)
        self.hidden_filters = hidden_filters  # filtres fixés par le lien du menu, sans liste déroulante
        self.list_title = list_title          # titre de la liste selon la requête : list_title(request)
        self.exclude_urls = exclude_urls
        self.create_url = create_url  # vues dédiées (ex. assistant d'enregistrement)
        self.update_url = update_url
        self.list_tabs = list_tabs  # callable → onglets affichés au-dessus de la liste
        self.header_links = header_links  # [(libellé, nom d'URL, icône)] affichés en tête de liste
        self.namespace = model.url_base.split(":")[0]
        REGISTRY[model] = self

    # -- helpers ---------------------------------------------------------
    @property
    def opts(self):
        return self.model._meta

    def perm(self, action):
        return f"{self.opts.app_label}.{action}_{self.opts.model_name}"

    def url(self, action):
        if action == "create" and self.create_url:
            return self.create_url
        if action == "update" and self.update_url:
            return self.update_url
        return f"{self.namespace}:{self.prefix}_{action}"

    def columns(self):
        return [c if isinstance(c, tuple) else (c, field_label(self.model, c)) for c in self.list_display]

    def get_form_class(self):
        if self.form_class:
            return self.form_class
        return modelform_factory(self.model, form=LimsModelForm, fields=self.fields,
                                 formfield_callback=lims_formfield)

    def filters(self, request):
        out = []
        for name in self.list_filter:
            f = self.opts.get_field(name)
            if f.choices:
                choices = [(str(k), v) for k, v in f.choices if k != ""]
            elif f.get_internal_type() == "BooleanField":
                choices = [("1", "Oui"), ("0", "Non")]
            elif f.is_relation:
                choices = [(str(o.pk), str(o)) for o in f.related_model.objects.all()[:200]]
            elif f.get_internal_type() == "CharField":
                values = (self.model.objects.exclude(**{name: ""}).order_by(name)
                          .values_list(name, flat=True).distinct()[:100])
                choices = [(v, v) for v in values]
            else:
                continue
            out.append({"name": name, "label": capfirst(f.verbose_name),
                        "choices": choices, "value": request.GET.get(name, "")})
        return out

    def date_filter_fields(self, request):
        return [{"name": n, "label": capfirst(self.opts.get_field(n).verbose_name).split(" (")[0],
                 "value": request.GET.get(n, "")}
                for n in self.date_filters]

    # -- views -----------------------------------------------------------
    def urls(self):
        crud = self
        base = {"crud": crud}

        class Mixin(LoginRequiredMixin, PermissionRequiredMixin):
            model = crud.model

            def get_context_data(self, **kwargs):
                ctx = super().get_context_data(**kwargs)
                ctx.update(base)
                return ctx

        class List(Mixin, ListView):
            permission_required = crud.perm("view")
            template_name = "generic/list.html"
            paginate_by = 25

            def get_queryset(self):
                qs = super().get_queryset()
                if crud.ordering:
                    qs = qs.order_by(*crud.ordering)
                q = self.request.GET.get("q", "").strip()
                if q and crud.search_fields:
                    qs = qs.filter(reduce(operator.or_, [Q(**{f"{f}__icontains": q}) for f in crud.search_fields]))
                for name in crud.list_filter:
                    v = self.request.GET.get(name)
                    if v not in (None, ""):
                        f = crud.opts.get_field(name)
                        if f.get_internal_type() == "BooleanField":
                            v = v == "1"
                        qs = filter_or_ignore(qs, **{name: v})
                for name in crud.hidden_filters:
                    if self.request.GET.get(name):
                        qs = filter_or_ignore(qs, **{name: self.request.GET[name]})
                for name in crud.date_filters:
                    d = parse_date(self.request.GET.get(name) or "")
                    if d:
                        qs = qs.filter(**{name: d})
                return qs

            def get(self, request, *args, **kwargs):
                if request.GET.get("export") == "csv":
                    if crud.exporter:
                        return crud.exporter(self.get_queryset())
                    return self.export(self.get_queryset())
                return super().get(request, *args, **kwargs)

            def export(self, qs):
                resp = HttpResponse(content_type="text/csv; charset=utf-8")
                resp["Content-Disposition"] = f'attachment; filename="{crud.prefix}.csv"'
                resp.write("﻿")  # BOM UTF-8 : Excel affiche correctement les accents
                names = ["code"] if hasattr(crud.model, "code") and "code" not in crud.fields else []
                names += [f for f in crud.fields]
                w = csv.writer(resp, delimiter=";")
                w.writerow([field_label(crud.model, n) for n in names])
                for obj in qs:
                    row = []
                    for n in names:
                        disp = getattr(obj, f"get_{n}_display", None)
                        v = disp() if disp else resolve(obj, n)
                        row.append("" if v is None else str(v))
                    w.writerow(row)
                return resp

            def get_context_data(self, **kwargs):
                ctx = super().get_context_data(**kwargs)
                ctx["columns"] = crud.columns()
                for name in crud.hidden_filters:  # liste non restreinte : la colonne reste utile
                    if not self.request.GET.get(name):
                        ctx["columns"].insert(2, (name, field_label(crud.model, name)))
                ctx["page_title"] = crud.list_title(self.request) if crud.list_title else None
                ctx["date_filters"] = crud.date_filter_fields(self.request)
                ctx["hidden_params"] = [(n, self.request.GET[n]) for n in crud.hidden_filters if self.request.GET.get(n)]
                ctx["hidden_query"] = urlencode(ctx["hidden_params"])
                ctx["tabs"] = crud.list_tabs() if crud.list_tabs else None
                ctx["filters"] = crud.filters(self.request)
                params = self.request.GET.copy()
                params.pop("page", None)
                ctx["querystring"] = params.urlencode()
                ctx["has_filters"] = ctx["querystring"] != ctx["hidden_query"]
                return ctx

        class Detail(Mixin, DetailView):
            permission_required = crud.perm("view")

            def get_template_names(self):
                return [crud.detail_template] if crud.detail_template else ["generic/detail.html"]

            def get_context_data(self, **kwargs):
                ctx = super().get_context_data(**kwargs)
                obj = self.object
                names = []
                for f in crud.opts.get_fields():
                    if f.concrete and not f.auto_created and f.name not in ("created_at", "updated_at"):
                        names.append(f.name)
                ctx["details"] = [(field_label(crud.model, n), n) for n in names]
                ctx["related"] = related_tables(obj, self.request.user)
                ctx["can_validate"] = (getattr(obj, "validatable", False) and not obj.is_validated
                                       and self.request.user.has_perm("core.validate_results"))
                if crud.extra_context:
                    ctx.update(crud.extra_context(obj, self.request))
                return ctx

        class FormMixin(Mixin):
            def get_template_names(self):
                return [crud.form_template] if crud.form_template else ["generic/form.html"]

            def get_form_class(self):
                return crud.get_form_class()

        class Create(FormMixin, CreateView):
            permission_required = crud.perm("add")

            def get_initial(self):
                initial = super().get_initial()
                for k, v in self.request.GET.items():
                    initial[k] = v
                for name in ("performed_by", "granted_by", "author", "owner"):  # utilisateur courant par défaut
                    try:
                        crud.opts.get_field(name)
                        initial.setdefault(name, self.request.user.pk)
                    except FieldDoesNotExist:
                        pass
                return initial

            def form_valid(self, form):
                if hasattr(form.instance, "granted_by_id") and not form.instance.granted_by_id:
                    form.instance.granted_by = self.request.user
                form.instance.created_by = self.request.user
                form.instance.updated_by = self.request.user
                resp = super().form_valid(form)
                log(self.request.user, "CREATE", self.object)
                messages.success(self.request, f"« {self.object} » enregistré.")
                nxt = safe_next(self.request, self.request.GET.get("next"), None)
                return HttpResponseRedirect(nxt) if nxt else resp

        class Update(FormMixin, UpdateView):
            permission_required = crud.perm("change")

            def get_object(self, queryset=None):
                obj = super().get_object(queryset)
                if getattr(obj, "validatable", False) and obj.is_validated \
                        and not self.request.user.has_perm("core.validate_results"):
                    raise PermissionDenied("Résultat validé : modification réservée aux biologistes.")
                return obj

            def form_valid(self, form):
                form.instance.updated_by = self.request.user
                changes = {f: str(form.cleaned_data.get(f)) for f in form.changed_data}
                resp = super().form_valid(form)
                log(self.request.user, "UPDATE", self.object, changes)
                messages.success(self.request, f"« {self.object} » modifié.")
                return resp

        class Delete(Mixin, DeleteView):
            permission_required = crud.perm("delete")
            template_name = "generic/confirm_delete.html"

            def get_success_url(self):
                return reverse(crud.url("list"))

            def form_valid(self, form):
                obj = self.object
                url, pk = obj.get_absolute_url(), obj.pk
                try:
                    resp = super().form_valid(form)
                except ProtectedError:
                    messages.error(self.request, "Suppression impossible : des objets liés existent.")
                    return HttpResponseRedirect(url)
                obj.pk = pk
                log(self.request.user, "DELETE", obj)
                messages.success(self.request, "Supprimé.")
                return resp

        class Validate(LoginRequiredMixin, PermissionRequiredMixin, View):
            permission_required = "core.validate_results"

            def post(self, request, pk):
                obj = get_object_or_404(crud.model, pk=pk)
                back = safe_next(request, request.POST.get("next"), obj.get_absolute_url())
                if obj.result_status != "DRAFT":  # déjà validé, ou annulé : rien à valider
                    messages.warning(request, f"« {obj} » est {obj.get_result_status_display().lower()} : "
                                              "validation impossible.")
                    return HttpResponseRedirect(back)
                comment = request.POST.get("validation_comment", "")[:2000]
                obj.validate(request.user, comment)
                log(request.user, "VALIDATE", obj, {"commentaire": comment} if comment else None)
                messages.success(request, f"« {obj} » validé.")
                return HttpResponseRedirect(back)

        p = self.prefix
        urls = [
            path(f"{p}/", List.as_view(), name=f"{p}_list"),
            path(f"{p}/nouveau/", Create.as_view(), name=f"{p}_create"),
            path(f"{p}/<int:pk>/", Detail.as_view(), name=f"{p}_detail"),
            path(f"{p}/<int:pk>/modifier/", Update.as_view(), name=f"{p}_update"),
            path(f"{p}/<int:pk>/supprimer/", Delete.as_view(), name=f"{p}_delete"),
        ]
        urls = [u for u in urls if u.name.removeprefix(f"{p}_") not in self.exclude_urls]
        if getattr(self.model, "validatable", False):
            urls.append(path(f"{p}/<int:pk>/valider/", Validate.as_view(), name=f"{p}_validate"))
        return urls


def related_tables(obj, user, limit=50):
    """Tableaux des objets liés (relations inverses) affichés sur une fiche."""
    tables = []
    for rel in obj._meta.related_objects:
        if not rel.one_to_many:
            continue
        crud = REGISTRY.get(rel.related_model)
        if not crud or not user.has_perm(crud.perm("view")):
            continue
        accessor = rel.get_accessor_name()
        qs = getattr(obj, accessor).all()
        qs = qs[:limit] if limit else qs
        tables.append({
            "crud": crud,
            "rows": qs,
            "columns": [c for c in crud.columns()
                        if c[0] != rel.field.name and not c[0].startswith(rel.field.name + "__")],
            "fk": rel.field.name,
            "can_add": user.has_perm(crud.perm("add")),
        })
    return tables

