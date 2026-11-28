from django import forms

from apps.core.crud import Crud
from apps.core.forms import LimsModelForm, lims_formfield

from .live import tabs as live_tabs

from .models import DST, Culture, GeneXpertTest, Microscopy, NPOCTest
from .qft_views import CRUDS as QFT_CRUDS

# result_status n'est pas éditable : il passe à « Validé » uniquement via l'action de validation.
RESULT_FIELDS = ["test_date", "performed_by", "comment"]


def culture_extra(c):
    rows = []
    if c.medium == "LJ":
        rows.append(("Tubes", c.tubes_display or "—"))
        rows.append(("Étape", c.stage[1]))
    if c.retreat_of_id:
        rows.append(("Retraitement de la culture du", f"{c.retreat_of.inoculated_on:%d/%m/%Y}"))
    if c.retreat_status == "RETREATED" and c.retreated_on:
        rows.append(("Retraitée le (nouvel ensemencement)", f"{c.retreated_on:%d/%m/%Y}"))
    return rows
class DSTForm(LimsModelForm):
    """Antibiogramme par groupe : un résultat (R / S / I / NF / NA) par antibiotique du groupe choisi."""

    class Meta:
        model = DST
        fields = ["sample", "culture", "method", "panel", *RESULT_FIELDS]
        formfield_callback = lims_formfield

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        names = dict(DST.DRUGS)
        current = self.instance.results or {}
        self.panel_drugs = {p: [f"res_{d}" for d in drugs] for p, drugs in DST.PANEL_DRUGS.items()}
        for panel, drugs in DST.PANEL_DRUGS.items():
            for d in drugs:
                self.fields[f"res_{d}"] = forms.ChoiceField(
                    label=f"{names[d]} ({d})", required=False, choices=[("", "—")] + DST.RESULTS,
                    initial=current.get(d, ""), widget=forms.Select(attrs={"class": "form-select dst-result",
                                                                           "data-panel": panel}))

    def clean(self):
        data = super().clean()
        panel = data.get("panel") or "FIRST"
        missing = [d for d in DST.PANEL_DRUGS[panel] if not data.get(f"res_{d}")]
        for d in missing:
            self.add_error(f"res_{d}", "Indiquez R, S, I, NF ou NA.")
        return data

    def save(self, commit=True):
        panel = self.cleaned_data["panel"]
        self.instance.results = {d: self.cleaned_data[f"res_{d}"] for d in DST.PANEL_DRUGS[panel]}
        return super().save(commit)


SEARCH = ["sample__code", "sample__patient__last_name", "sample__patient__code"]

XDR_FIELDS = ["inh_result", "fq_result", "amk_result", "kan_result", "cap_result", "eto_result"]


class GeneXpertForm(LimsModelForm):
    """GNX-RIF (Ultra) : seule la rifampicine ; GNX-XDR : INH, FLQ, AMK, KAN, CAP, ETH (pas de RIF)."""

    class Meta:
        model = GeneXpertTest
        fields = ["sample", "assay", "cartridge_lot", "instrument", "mtb_result", "rif_result", *XDR_FIELDS,
                  "error_code", *RESULT_FIELDS]
        formfield_callback = lims_formfield

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["rif_result", *XDR_FIELDS]:   # masqués selon le test : « Non applicable » par défaut
            self.fields[name].required = False

    def clean(self):
        data = super().clean()
        for name in ["rif_result", *XDR_FIELDS]:
            data[name] = data.get(name) or "NA"
        if data.get("assay") == "ULTRA":
            for name in XDR_FIELDS:
                data[name] = "NA"
        elif data.get("assay") == "XDR":
            data["rif_result"] = "NA"
        return data

CRUDS = [
    Crud(
        GeneXpertTest, "genexpert",
        fields=GeneXpertForm.Meta.fields,
        form_class=GeneXpertForm,
        form_template="diagnostic/genexpert_form.html",
        list_display=["sample", "sample__patient", "assay", "test_date", "mtb_result", "rif_result",
                      "inh_result", "fq_result", "result_status"],
        search_fields=SEARCH + ["cartridge_lot"],
        list_filter=["assay", "mtb_result", "rif_result", "result_status"],
        icon="bi-cpu",
        list_tabs=lambda: live_tabs("genexpert", "list"),
    ),
    Crud(
        NPOCTest, "npoc",
        fields=["sample", "assay", "device_serial", "kit_lot", "mtb_result", "signal_value", "error_code",
                *RESULT_FIELDS],
        list_display=["sample", "sample__patient", "assay", "test_date", "mtb_result", "signal_value",
                      "result_status"],
        search_fields=SEARCH + ["kit_lot", "device_serial"],
        list_filter=["mtb_result", "result_status"],
        icon="bi-lightning-charge",
        list_tabs=lambda: live_tabs("npoc", "list"),
    ),
    Crud(
        Microscopy, "microscopy",
        fields=["sample", "method", "slide_number", "grade", "afb_count", *RESULT_FIELDS],
        list_display=["sample", "sample__patient", "method", "test_date", "grade", "afb_count", "result_status"],
        search_fields=SEARCH + ["slide_number"],
        list_filter=["method", "grade", "result_status"],
        icon="bi-eye",
    ),
    Crud(
        Culture, "culture",
        # pas de « date d'analyse » : pour une culture, c'est la date d'ensemencement (mise en étuve)
        fields=["sample", "medium", "tube_count", "decontamination", "inoculated_on", "incubator", "growth_on",
                "sd_test", "sd_date", "result", "result_date", "lj_grade", "colony_count", "zn_confirmation",
                "identification", "id_method", "performed_by", "comment"],
        list_display=["sample", "sample__patient", "inoculated_on", ("tubes_display", "Tubes"), "result",
                      "result_date", "ttp_days", "identification", "result_status"],
        search_fields=SEARCH + ["tube_number"],
        list_filter=["result", "identification", "result_status"],
        date_filters=["inoculated_on"],
        hidden_filters=["medium"],   # fixé par le menu : Culture LJ / Culture MGIT
        list_title=lambda request: {"LJ": "Culture LJ", "MGIT": "Culture MGIT"}.get(request.GET.get("medium")),
        icon="bi-moisture",
        extra_context=lambda obj, request: {"extra_details": culture_extra(obj)},
    ),
    Crud(
        DST, "dst",
        fields=["sample", "culture", "method", "panel", *RESULT_FIELDS],
        form_class=DSTForm,
        form_template="diagnostic/dst_form.html",
        extra_context=lambda obj, request: {"extra_details": [(n, f"{r} — {lbl}" if r else "—")
                                                             for _, n, r, lbl in obj.drug_results]},
        list_display=["sample", "sample__patient", "method", "panel", ("results_display", "Résultats"),
                      "result_status"],
        search_fields=SEARCH,
        list_filter=["method", "panel", "result_status"],
        icon="bi-capsule",
    ),
]
CRUDS += QFT_CRUDS   # plaques ELISA et résultats QuantiFERON (qft_views.py)
