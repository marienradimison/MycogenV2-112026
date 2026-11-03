"""Suivi en temps réel des automates GeneXpert et NPOC (page d'accueil des modules 03a et 03b)."""
from datetime import timedelta

from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from apps.instruments.models import Instrument, InstrumentMessage
from apps.instruments.views import running_tests

from .models import GeneXpertTest, NPOCTest

POSITIVE = ["TRACE", "VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH", "DETECTED"]
FAILED = ["INVALID", "ERROR", "NO_RESULT"]

MODULES = {
    "genexpert": {
        "title": "GeneXpert", "icon": "bi-cpu", "kind": "GENEXPERT", "model": GeneXpertTest,
        "list": "diagnostic:genexpert_list", "create": "diagnostic:genexpert_create",
        "live": "diagnostic:genexpert_live", "perm": "diagnostic.view_genexperttest",
        # durée d'un test (minutes) : Xpert MTB/RIF Ultra ≈ 80 min, MTB/XDR ≈ 90 min
        "durations": {"GNX-RIF": 80, "GNX-XDR": 90}, "default_duration": 80,
    },
    "npoc": {
        "title": "NPOC (Pluslife)", "icon": "bi-lightning-charge", "kind": "PLUSLIFE", "model": NPOCTest,
        "list": "diagnostic:npoc_list", "create": "diagnostic:npoc_create",
        "live": "diagnostic:npoc_live", "perm": "diagnostic.view_npoctest",
        "durations": {}, "default_duration": 45,
    },
}


def tabs(module, active):
    cfg = MODULES[module]
    return [("live", "Suivi en temps réel", "bi-broadcast", reverse(cfg["live"]), active == "live"),
            ("list", "Tests réalisés", "bi-list-ul", reverse(cfg["list"]), active == "list")]


def running_rows(inst, cfg, now):
    rows = []
    for q in running_tests(inst):
        codes = q.sample.requested_analyses if q.sample else []
        duration = next((cfg["durations"][c] for c in reversed(codes) if c in cfg["durations"]),
                        cfg["default_duration"])
        elapsed = (now - q.received_at).total_seconds() / 60
        rows.append({
            "msg": q, "sample": q.sample, "ref": q.sample_ref, "started": q.received_at,
            "elapsed": int(elapsed), "duration": duration, "progress": min(100, int(elapsed / duration * 100)),
            "end": q.received_at + timedelta(minutes=duration), "late": elapsed > duration + 15,
            "overdue": duration < elapsed <= duration + 15,
        })
    return rows


def build_context(module):
    cfg = MODULES[module]
    now, today = timezone.now(), timezone.localdate()
    model = cfg["model"]
    instruments = []
    for inst in Instrument.objects.filter(kind=cfg["kind"], active=True).select_related("room"):
        instruments.append({
            "obj": inst, "running": running_rows(inst, cfg, now),
            "online": bool(inst.last_seen and now - inst.last_seen < timedelta(minutes=30)),
            "today": inst.messages.filter(kind="RESULT", received_at__date=today).count(),
        })
    tests_today = model.objects.filter(test_date=today)
    stats = {
        "running": sum(len(i["running"]) for i in instruments),
        "today": tests_today.count(),
        "positive": tests_today.filter(mtb_result__in=POSITIVE).count(),
        "failed": tests_today.filter(mtb_result__in=FAILED).count(),
        "to_validate": model.objects.filter(result_status="DRAFT").count(),
        "unmatched": InstrumentMessage.objects.filter(instrument__kind=cfg["kind"],
                                                      status__in=["UNMATCHED", "ERROR", "NEW"]).count(),
    }
    stats["rr"] = tests_today.filter(rif_result="DETECTED").count() if module == "genexpert" else None
    recent = model.objects.select_related("sample", "sample__patient").order_by("-created_at")[:12]
    return {"cfg": cfg, "module": module, "instruments": instruments, "stats": stats, "recent": recent,
            "now": now, "tabs": tabs(module, "live")}


def make_view(module):
    @login_required
    @permission_required(MODULES[module]["perm"], raise_exception=True)
    def view(request):
        ctx = build_context(module)
        template = "diagnostic/_live_body.html" if request.GET.get("partial") else "diagnostic/live.html"
        return render(request, template, ctx)
    view.__name__ = f"{module}_live"
    return view


genexpert_live = make_view("genexpert")
npoc_live = make_view("npoc")
