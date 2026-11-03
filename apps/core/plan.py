"""Plan de masse interactif de l'Unité des Mycobactéries."""
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render
from django.urls import reverse

from . import floorplan
from .models import Room


def room_payload(room, user):
    can_change = user.has_perm("core.change_room")
    return {
        "id": room.pk, "zone": room.zone, "number": room.number, "name": room.name,
        "usage": room.get_usage_display() if room.usage else "Usage non renseigné", "usage_code": room.usage,
        "color": room.color,
        "responsible": (room.responsible.get_full_name() or room.responsible.username) if room.responsible else "",
        "phone": room.phone_ext, "area": str(room.area_m2) if room.area_m2 is not None else "",
        "access": room.access, "notes": room.notes, "active": room.active,
        "url": room.get_absolute_url(),
        "edit_url": reverse("core:room_update", args=[room.pk]) if can_change else "",
        "instruments": [{"name": i.name, "kind": i.get_kind_display(), "url": i.get_absolute_url()}
                        for i in room.instruments.all()],
        "units": [{"name": u.name, "kind": u.get_type_display(), "url": u.get_absolute_url()}
                  for u in room.storage_units.all()],
        "equipment": [{"name": str(e), "kind": e.get_status_display(), "alert": e.alert, "url": e.get_absolute_url()}
                      for e in room.equipment.all() if e.status != "RETIRED"],
        "people": [{"name": a.person, "kind": a.get_level_display() + (" · expiré" if a.state == "expired" else ""),
                    "alert": "danger" if a.state == "expired" else ("warning" if a.state == "soon" else ""),
                    "url": a.get_absolute_url()} for a in room.accesses.all() if not a.revoked],
        "add_equipment": (reverse("quality:equipment_create") + f"?room={room.pk}")
        if user.has_perm("quality.add_equipment") else "",
        "add_access": (reverse("quality:access_create") + f"?room={room.pk}")
        if user.has_perm("quality.add_roomaccess") else "",
    }


@login_required
@permission_required("core.view_facility", raise_exception=True)
def floor_plan(request):
    highlight = request.GET.get("salle", "").strip()
    level = request.GET.get("niveau", "")
    if level not in floorplan.LEVELS:
        found = Room.objects.filter(number__iexact=highlight).first() if highlight else None
        level = floorplan.ZONE_LEVEL.get(found.zone, floorplan.DEFAULT_LEVEL) if found else floorplan.DEFAULT_LEVEL
    plan = floorplan.LEVELS[level]
    level_keys = [k for k, lv in floorplan.ZONE_LEVEL.items() if lv == level]
    rooms = {r.zone: r for r in Room.objects.filter(zone__in=level_keys).select_related("responsible")
             .prefetch_related("instruments", "storage_units", "equipment", "accesses__user")}
    zones = floorplan.zones(level)
    for z in zones:
        z["room"] = rooms.get(z["key"])
    stairs = [{**s, "lines": floorplan.stair_lines(s)} for s in plan["stairs"]]
    used = sorted({r.usage or "NONE" for r in rooms.values()})
    legend = [(code, label, Room.COLORS[code]) for code, label in Room.USAGES if code in used]
    if "NONE" in used:
        legend.append(("NONE", "Usage non renseigné", "#c3ced2"))
    return render(request, "core/floor_plan.html", {
        "zones": zones, "viewbox": plan["viewbox"], "corridor": floorplan.points(plan["corridor"]),
        "corridor_label": plan["corridor_label"], "building": floorplan.points(plan["building"]),
        "walls": plan["walls"], "doors": plan["doors"], "stairs": stairs, "fixtures": plan["fixtures"],
        "level": level, "level_label": plan["label"],
        "levels": [(k, v["short"], k == level) for k, v in floorplan.LEVELS.items()],
        "rooms_json": {r.zone: room_payload(r, request.user) for r in rooms.values()},
        "legend": legend, "assigned": len(rooms), "total": len(zones),
        "can_add": request.user.has_perm("core.add_room"),
        "highlight": highlight,
    })
