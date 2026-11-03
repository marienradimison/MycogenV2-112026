from django import forms

from apps.core.crud import Crud
from apps.core.forms import LimsModelForm, lims_formfield

from .models import LPATest, PCRAssay, Project, ProjectCase, SequencingLibrary, SequencingRun, Study

RESULT_FIELDS = ["test_date", "performed_by", "comment"]
SEARCH = ["sample__code", "sample__patient__last_name", "sample__patient__code"]

class StudyForm(LimsModelForm):
    class Meta:
        model = Study
        fields = ["project", "code", "name", "case_mode", "cases", "case_label", "active"]
        formfield_callback = lims_formfield

    def clean(self):
        data = super().clean()
        project, mode, cases = data.get("project"), data.get("case_mode"), data.get("cases")
        if mode == "LIST":
            if not cases:
                self.add_error("cases", "Choisissez au moins un cas pour cette étude.")
            elif project and any(c.project_id != project.pk for c in cases):
                self.add_error("cases", f"Les cas doivent appartenir au projet {project.code}.")
        else:
            data["cases"] = []
        if mode != "TEXT":
            data["case_label"] = ""
        return data


def case_config(study, request=None):
    if study.case_mode == "LIST":
        value = ", ".join(c.name for c in study.cases.all()) or "—"
        return {"extra_details": [("Cas autorisés", value)]}
    if study.case_mode == "TEXT":
        return {"extra_details": [("Libellé du champ", study.case_label or "Cas")]}
    return {}


CRUDS = [
    Crud(
        Project, "project",
        fields=["code", "title", "principal_investigator", "members", "funder", "ethics_ref",
                "ethics_expiry", "start_date", "end_date", "status", "description"],
        list_display=["code", "title", "principal_investigator", "funder", "start_date", "end_date", "status"],
        search_fields=["code", "title", "principal_investigator", "funder"],
        list_filter=["status"],
        icon="bi-journal-bookmark",
    ),
    Crud(
        Study, "study",
        fields=["project", "code", "name", "case_mode", "cases", "case_label", "active"],
        form_class=StudyForm,
        extra_context=case_config,
        list_display=["code", "project", "name", "case_mode", "active"],
        search_fields=["code", "name", "project__code"],
        list_filter=["project", "case_mode", "active"],
        icon="bi-collection",
    ),
    Crud(
        ProjectCase, "case",
        fields=["project", "name", "description", "active"],
        list_display=["name", "project", "description", "active"],
        search_fields=["name", "project__code"],
        list_filter=["project", "active"],
        icon="bi-people",
    ),
    Crud(
        SequencingRun, "run",
        fields=["run_id", "technology", "platform", "project", "library_kit", "flowcell", "run_date",
                "operator", "status", "total_yield_gb", "data_path", "notes"],
        list_display=["run_id", "technology", "platform", "project", "run_date", "status", "total_yield_gb"],
        search_fields=["run_id", "flowcell", "library_kit"],
        list_filter=["technology", "platform", "status", "project"],
        icon="bi-diagram-3",
    ),
    Crud(
        SequencingLibrary, "library",
        fields=["run", "sample", "dna", "library_id", "barcode", "input_conc", "library_conc", "reads",
                "mean_depth", "coverage_pct", "qc_pass", "notes"],
        list_display=["library_id", "run", "sample", "barcode", "reads", "mean_depth", "coverage_pct", "qc_pass"],
        search_fields=["library_id", "barcode", "run__run_id", "sample__code"],
        list_filter=["qc_pass", "run"],
        icon="bi-upc",
    ),
    Crud(
        PCRAssay, "pcr",
        fields=["sample", "project", "assay", "instrument", "plate_id", "reference_gene", "ref_ct",
                "ct_gbp2", "ct_fcgr1b", "ct_serping1", "ct_tubgcp6", "ct_trmt2a", "ct_sdr39u1",
                "ct_gbp5", "ct_dusp3", "ct_klf2", "score", "threshold", *RESULT_FIELDS],
        list_display=["sample", "assay", "test_date", "plate_id", "score", "threshold", "outcome", "result_status"],
        search_fields=SEARCH + ["plate_id"],
        list_filter=["assay", "outcome", "project", "result_status"],
        icon="bi-thermometer-half",
        form_template="research/pcr_form.html",
    ),
    Crud(
        LPATest, "lpa",
        fields=["sample", "project", "kit", "kit_lot", "source", "mtbc_detected", "species", "rif",
                "inh_katg", "inh_inha", "fq", "sli", "missing_wt", "mutations", *RESULT_FIELDS],
        list_display=["sample", "kit", "test_date", "mtbc_detected", "rif", "inh_katg", "inh_inha", "fq", "sli",
                      "result_status"],
        search_fields=SEARCH + ["mutations"],
        list_filter=["kit", "rif", "inh_katg", "fq", "result_status"],
        icon="bi-bar-chart-steps",
    ),
]
