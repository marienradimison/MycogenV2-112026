"""PCR par run : le run porte la signature, la plaque, le thermocycleur, le seuil ; chaque résultat y est rattaché."""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def group_into_runs(apps, schema_editor):
    """Résultats existants : même plaque (à défaut même signature et même date) = même run."""
    PCRAssay = apps.get_model("research", "PCRAssay")
    PCRRun = apps.get_model("research", "PCRRun")
    for r in PCRAssay.objects.order_by("pk"):
        run_id = r.plate_id or f"{r.assay}-{r.test_date:%Y%m%d}"
        run, _ = PCRRun.objects.get_or_create(run_id=run_id, defaults={
            "assay": r.assay, "project_id": r.project_id, "instrument": r.instrument,
            "reference_gene": r.reference_gene, "threshold": r.threshold, "run_date": r.test_date,
            "operator_id": r.performed_by_id, "status": "DONE"})
        r.run = run
        r.save(update_fields=["run"])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("research", "0004_study_case_label_study_case_mode_study_cases"),
    ]

    operations = [
        migrations.CreateModel(
            name="PCRRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifié le")),
                ("run_id", models.CharField(max_length=60, unique=True, verbose_name="identifiant du run / plaque")),
                ("assay", models.CharField(choices=[("RISK6", "RISK6"), ("SWEENEY3", "Sweeney3"), ("OTHER", "Autre")], max_length=10, verbose_name="signature")),
                ("instrument", models.CharField(blank=True, max_length=60, verbose_name="thermocycleur")),
                ("kit_lot", models.CharField(blank=True, max_length=60, verbose_name="lot du kit")),
                ("reference_gene", models.CharField(blank=True, max_length=30, verbose_name="gène de référence")),
                ("threshold", models.DecimalField(blank=True, decimal_places=3, max_digits=8, null=True, verbose_name="seuil de positivité")),
                ("run_date", models.DateField(default=django.utils.timezone.localdate, verbose_name="date du run")),
                ("status", models.CharField(choices=[("PLANNED", "Planifié"), ("RUNNING", "En cours"), ("DONE", "Terminé"), ("FAILED", "Échec")], default="PLANNED", max_length=8, verbose_name="statut")),
                ("notes", models.TextField(blank=True, verbose_name="remarques")),
                ("created_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="créé par")),
                ("operator", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="opérateur")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pcr_runs", to="research.project", verbose_name="projet")),
                ("updated_by", models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL, verbose_name="modifié par")),
            ],
            options={"verbose_name": "run PCR", "verbose_name_plural": "runs PCR", "ordering": ["-run_date", "-id"]},
        ),
        migrations.AddField(
            model_name="pcrassay", name="run",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="results", to="research.pcrrun", verbose_name="run PCR"),
        ),
        migrations.RunPython(group_into_runs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="pcrassay", name="run",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="results", to="research.pcrrun", verbose_name="run PCR"),
        ),
        migrations.RemoveField(model_name="pcrassay", name="assay"),
        migrations.RemoveField(model_name="pcrassay", name="instrument"),
        migrations.RemoveField(model_name="pcrassay", name="plate_id"),
        migrations.RemoveField(model_name="pcrassay", name="project"),
        migrations.RemoveField(model_name="pcrassay", name="reference_gene"),
        migrations.RemoveField(model_name="pcrassay", name="threshold"),
    ]
