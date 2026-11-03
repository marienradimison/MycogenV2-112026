from apps.core.crud import Crud

from .models import Analysis, Pipeline

CRUDS = [
    Crud(
        Analysis, "analysis",
        fields=["library", "sample", "pipeline", "analyst", "run_date", "status", "species", "lineage",
                "sublineage", "spoligotype", "drug_profile", "resistance_mutations", "mean_depth",
                "genome_coverage", "mapped_pct", "cluster", "output_path", "report_file", "notes"],
        list_display=["code", "sample", "library", "pipeline", "run_date", "lineage", "sublineage",
                      "drug_profile", "status"],
        search_fields=["code", "sample__code", "library__library_id", "lineage", "sublineage", "cluster",
                       "resistance_mutations"],
        list_filter=["status", "drug_profile", "pipeline", "lineage"],
        icon="bi-terminal",
    ),
    Crud(
        Pipeline, "pipeline",
        fields=["name", "version", "tool_type", "reference", "database_version", "repository", "active",
                "description"],
        list_display=["name", "version", "tool_type", "reference", "database_version", "active"],
        search_fields=["name", "tool_type"],
        list_filter=["active"],
        icon="bi-gear-wide-connected",
    ),
]
