from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"
    verbose_name = "Réception & patients"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from .status import result_changed

        post_save.connect(result_changed, dispatch_uid="sample_status_save")
        post_delete.connect(result_changed, dispatch_uid="sample_status_delete")
