from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.crud import Crud, log
from apps.core.models import Sample

from .handlers import process
from .models import Instrument, InstrumentMessage

instrument_crud = Crud(
    Instrument, "instrument",
    fields=["name", "kind", "serial_number", "room", "location", "connection", "host", "port", "serial_port",
            "baudrate", "folder", "reply_to_queries", "active", "notes"],
    list_display=["name", "kind", "room", "connection", "port", "last_seen", "active"],
    search_fields=["name", "serial_number", "location"],
    list_filter=["kind", "connection", "active"],
    icon="bi-hdd-network",
)

RUNNING_WINDOW = timedelta(hours=4)


def running_tests(instrument):
    """Requêtes hôte récentes sans résultat reçu ensuite = tests en cours sur l'automate."""
    since = timezone.now() - RUNNING_WINDOW
    queries = instrument.messages.filter(kind="QUERY", received_at__gte=since).select_related("sample")
    done = set(instrument.messages.filter(kind="RESULT", received_at__gte=since)
               .values_list("sample_ref", "received_at"))
    out, seen = [], set()
    for q in queries:
        if q.sample_ref in seen:
            continue
        seen.add(q.sample_ref)
        if not any(ref == q.sample_ref and at > q.received_at for ref, at in done):
            out.append(q)
    return out


@login_required
@permission_required("instruments.view_instrumentmessage", raise_exception=True)
def monitor(request):
    now = timezone.now()
    cards = []
    for inst in Instrument.objects.filter(active=True):
        cards.append({
            "instrument": inst,
            "running": running_tests(inst),
            "recent": inst.messages.filter(kind="RESULT").select_related("sample")[:6],
            "online": inst.last_seen and now - inst.last_seen < timedelta(minutes=30),
            "today": inst.messages.filter(kind="RESULT", received_at__date=timezone.localdate()).count(),
        })
    pending = InstrumentMessage.objects.filter(status__in=["UNMATCHED", "ERROR", "NEW"]).count()
    return render(request, "instruments/monitor.html", {"cards": cards, "pending": pending})


@login_required
@permission_required("instruments.view_instrumentmessage", raise_exception=True)
def message_list(request):
    qs = InstrumentMessage.objects.select_related("instrument", "sample")
    status = request.GET.get("status", "")
    if status == "todo":
        qs = qs.filter(status__in=["UNMATCHED", "ERROR", "NEW"])
    elif status:
        qs = qs.filter(status=status)
    if request.GET.get("instrument"):
        qs = qs.filter(instrument_id=request.GET["instrument"])
    if request.GET.get("q"):
        qs = qs.filter(sample_ref__icontains=request.GET["q"].strip())
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "instruments/message_list.html", {
        "page_obj": page, "statuses": InstrumentMessage.STATUS, "instruments": Instrument.objects.all(),
        "querystring": params.urlencode(),
    })


@login_required
@permission_required("instruments.view_instrumentmessage", raise_exception=True)
def message_detail(request, pk):
    msg = get_object_or_404(InstrumentMessage.objects.select_related("instrument", "sample"), pk=pk)
    return render(request, "instruments/message_detail.html", {
        "msg": msg, "raw_lines": msg.raw.replace("\r\n", "\r").replace("\n", "\r").split("\r"),
    })


@login_required
@require_POST
@permission_required("instruments.change_instrumentmessage", raise_exception=True)
def message_action(request, pk):
    msg = get_object_or_404(InstrumentMessage, pk=pk)
    action = request.POST.get("action")
    if action == "ignore":
        msg.status = "IGNORED"
        msg.save()
        messages.info(request, "Message ignoré.")
    elif action in ("assign", "retry"):
        sample = None
        if action == "assign":
            sample = Sample.objects.filter(code__iexact=request.POST.get("sample_code", "").strip()).first()
            if sample is None:
                messages.error(request, "Code échantillon introuvable.")
                return redirect(msg)
        process(msg, sample=sample)
        if msg.status == "IMPORTED":
            log(request.user, "UPDATE", msg.result, {"import": f"message automate #{msg.pk}"})
            messages.success(request, f"Résultat importé : {msg.summary}")
        else:
            messages.warning(request, f"{msg.get_status_display()} — {msg.summary or msg.detail}")
    return redirect(msg)
