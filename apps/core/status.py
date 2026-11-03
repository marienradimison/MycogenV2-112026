"""Statut automatique des échantillons, recalculé à chaque saisie, modification ou validation de résultat.

    Reçu                     saisie faite, aucune analyse commencée
    En cours d'analyse       au moins une analyse demandée n'a pas encore de résultat
    En attente de validation résultats complets, au moins un résultat non validé
    Terminé                  tous les résultats de toutes les analyses sont validés
    Rejeté                   échantillon non conforme
"""


def has_result(obj):
    """Une culture en étuve (« En cours ») n'a pas encore de résultat."""
    if obj._meta.model_name == "culture":
        return obj.result != "PENDING"
    return True


def compute_status(sample):
    from .analyses import families, sample_analyses

    if not sample.conform:
        return "REJECTED"
    results = {}   # tous les résultats saisis, même sans code dans la bibliothèque
    for model, _, _, _ in families().values():
        for r in model.objects.filter(sample=sample):
            results[(model, r.pk)] = r
    results = list(results.values())
    if not results:
        return "RECEIVED"
    analyses = sample_analyses(sample)
    if any(not a["results"] for a in analyses) or not all(has_result(r) for r in results):
        return "IN_PROGRESS"
    if all(getattr(r, "is_validated", True) for r in results):
        return "COMPLETED"
    return "PENDING_VALIDATION"


def refresh_status(sample):
    """Met à jour le statut en base (sans toucher à la date de modification) ; renvoie le nouveau statut."""
    from .models import Sample

    status = compute_status(sample)
    if status != sample.status:
        Sample.objects.filter(pk=sample.pk).update(status=status)
        sample.status = status
    return status


def result_changed(sender, instance, **kwargs):
    """Signal post_save / post_delete des résultats : recalcul du statut de l'échantillon."""
    from .analyses import families
    from .models import Sample

    if isinstance(instance, Sample):   # conformité / analyses demandées modifiées (post_save seulement)
        if "created" in kwargs:
            refresh_status(instance)
        return
    if not any(isinstance(instance, model) for model, *_ in families().values()):
        return
    fresh = Sample.objects.filter(pk=instance.sample_id).first() if instance.sample_id else None
    if fresh:
        refresh_status(fresh)
