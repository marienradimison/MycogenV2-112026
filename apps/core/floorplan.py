"""Géométrie du plan de masse de l'Unité des Mycobactéries, sur deux niveaux.

- « etage » : étage de l'unité (salles 1 à 21) ;
- « p3 »    : laboratoire P3, isolé au RDC, accessible par l'escalier entre les salles 7 et 8.

Coordonnées dans le repère des plans d'origine (1920 × 1080). Chaque salle est un polygone repéré par une
clé de zone fixe et unique (ex. « 12b », « P3-04 ») ; numéros, noms et usages se gèrent dans l'administration
(modèle Room).
"""


def rect(x1, y1, x2, y2):
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


LEVELS = {
    "etage": {
        "label": "Étage — Unité des Mycobactéries",
        "short": "Étage",
        "viewbox": "10 240 1860 700",
        "building": [(180, 257), (1855, 257), (1855, 887), (180, 887)],
        "corridor": rect(180, 520, 1855, 623),
        "corridor_label": (210, 579),
        # (clé, polygone, point d'étiquette ou None = centre)
        "zones": [
            # --- Côté nord (de gauche à droite) ---
            ("21", [(180, 257), (397, 257), (397, 401), (357, 401), (357, 520), (180, 520)], (268, 400)),
            ("20", [(397, 257), (528, 257), (528, 377), (499, 377), (499, 520), (357, 520), (357, 401), (397, 401)], (449, 405)),
            ("19", [(528, 257), (634, 257), (634, 520), (499, 520), (499, 377), (528, 377)], (577, 398)),
            ("18", rect(634, 257, 740, 520), None),
            ("17", rect(740, 257, 863, 520), None),
            ("16b", rect(863, 257, 975, 410), None),
            ("16a", rect(863, 410, 975, 520), None),
            ("15b", rect(975, 257, 1088, 338), None),
            ("15a", rect(975, 338, 1088, 520), None),
            ("14b", [(1088, 257), (1311, 257), (1311, 520), (1197, 520), (1197, 410), (1088, 410)], (1200, 340)),
            ("14a", rect(1088, 410, 1197, 520), None),
            ("13c", rect(1311, 257, 1433, 422), None),
            ("13b", rect(1311, 422, 1433, 471), None),
            ("13a", rect(1311, 471, 1433, 520), None),
            ("12b", rect(1433, 257, 1540, 471), None),   # ancienne 12b + 12c fusionnées
            ("12a", rect(1433, 471, 1540, 520), None),
            ("11", rect(1540, 257, 1650, 520), None),
            ("10", rect(1650, 257, 1855, 520), None),
            # --- Côté sud ---
            ("1", rect(180, 623, 295, 887), (236, 703)),
            ("2", rect(295, 623, 407, 887), (357, 703)),
            ("3", rect(407, 623, 517, 887), (463, 770)),
            ("4", rect(517, 623, 745, 887), None),
            ("5a", rect(745, 623, 858, 707), None),
            ("5b", rect(745, 707, 858, 887), None),
            ("6a", rect(858, 623, 966, 819), None),
            ("6b", rect(858, 819, 966, 887), None),
            ("7", rect(966, 623, 1193, 887), None),
            ("8", rect(1295, 623, 1650, 887), (1446, 770)),
            ("9", rect(1650, 623, 1855, 887), None),
        ],
        # Cloisons intérieures sans numéro propre (locaux rattachés à une salle)
        "walls": [
            (180, 790, 407, 790), (245, 790, 245, 887), (345, 790, 345, 887),   # douches / WC (1 et 2)
            (450, 685, 517, 685),                                                # réduit de la salle 3
            (1540, 623, 1540, 712), (1540, 712, 1650, 712),                      # local de la salle 8
            (1247, 628, 1247, 760),                                              # limon de l'escalier
        ],
        # Portes : (x1, y1, x2, y2, type) — « door » normale (bleu), « slide » coulissante (vert)
        "doors": [
            (310, 520, 347, 520, "door"), (452, 520, 490, 520, "door"), (588, 520, 626, 520, "door"),
            (642, 520, 680, 520, "door"), (818, 520, 855, 520, "door"), (873, 520, 910, 520, "door"),
            (1043, 520, 1080, 520, "door"), (1097, 520, 1135, 520, "door"), (1267, 520, 1304, 520, "door"),
            (1385, 520, 1422, 520, "door"), (1436, 520, 1492, 520, "slide"), (1548, 520, 1585, 520, "door"),
            (1661, 520, 1698, 520, "door"),
            (863, 292, 863, 330, "door"), (982, 338, 1020, 338, "door"),
            (1373, 422, 1430, 422, "slide"), (1433, 425, 1433, 470, "slide"), (1436, 471, 1492, 471, "slide"),
            (184, 524, 184, 620, "door"), (1851, 524, 1851, 620, "door"),
            (250, 623, 287, 623, "door"), (302, 623, 338, 623, "door"), (473, 623, 510, 623, "door"),
            (527, 623, 563, 623, "door"), (816, 623, 852, 623, "door"), (866, 623, 903, 623, "door"),
            (1053, 623, 1090, 623, "door"), (1203, 623, 1240, 623, "door"), (1306, 623, 1343, 623, "door"),
            (1662, 623, 1698, 623, "door"),
            (412, 685, 449, 685, "door"),
            (217, 790, 240, 790, "door"), (251, 790, 275, 790, "door"), (314, 790, 337, 790, "door"),
            (352, 790, 375, 790, "door"),
            (862, 819, 918, 819, "slide"), (858, 840, 858, 878, "door"), (1540, 652, 1540, 690, "door"),
        ],
        # Escaliers ; « to » = niveau atteint (cliquable)
        "stairs": [
            {"x": 1193, "y": 623, "w": 102, "h": 264, "steps": (1200, 628, 1292, 775), "to": "p3",
             "label": "Escalier ↓ RDC (P3)", "lx": 1244, "ly": 830},
            {"x": 108, "y": 497, "w": 67, "h": 359, "steps": (110, 648, 173, 852)},
            {"x": 22, "y": 856, "w": 153, "h": 72, "steps": (24, 858, 108, 926), "dir": "v"},
        ],
        "fixtures": [
            {"kind": "basin", "x": 187, "y": 630, "w": 18, "h": 98},
            {"kind": "basin", "x": 385, "y": 630, "w": 18, "h": 98},
            {"kind": "shower", "x": 188, "y": 848, "w": 52, "h": 34},
            {"kind": "shower", "x": 350, "y": 848, "w": 52, "h": 34},
            {"kind": "wc", "cx": 270, "cy": 862}, {"kind": "wc", "cx": 320, "cy": 862},
            {"kind": "sink", "cx": 294, "cy": 663}, {"kind": "sink", "cx": 303, "cy": 706},
            {"kind": "sink", "cx": 303, "cy": 738},
        ],
    },
    "p3": {
        "label": "RDC — Laboratoire P3",
        "short": "RDC · P3",
        "viewbox": "330 50 1370 890",
        "building": [(862, 70), (1673, 70), (1673, 907), (862, 907)],
        # couloir + renfoncement de l'autoclave
        "corridor": [(862, 800), (1134, 800), (1134, 623), (1284, 623), (1284, 800), (1673, 800),
                     (1673, 907), (862, 907)],
        "corridor_label": (900, 862),
        "zones": [
            ("P3-05", rect(862, 70, 1284, 334), None),
            ("P3-07", rect(1284, 70, 1673, 433), None),
            ("P3-04", [(862, 334), (1284, 334), (1284, 623), (999, 623), (999, 433), (862, 433)], (1123, 491)),
            ("P3-02", rect(862, 433, 999, 623), None),
            ("P3-06", rect(1284, 433, 1673, 800), None),
            ("P3-01", rect(862, 623, 999, 800), None),
            ("P3-03", rect(999, 623, 1134, 800), None),
            ("P3-A", rect(1148, 623, 1226, 727), (1187, 675)),   # emplacement de l'autoclave
        ],
        "walls": [],
        "doors": [
            (1191, 334, 1258, 334, "door"), (1284, 354, 1284, 421, "door"), (1284, 546, 1284, 613, "door"),
            (999, 546, 999, 613, "door"), (928, 623, 995, 623, "door"), (1036, 623, 1103, 623, "door"),
            (928, 800, 995, 800, "door"), (1036, 800, 1103, 800, "door"), (862, 825, 862, 890, "door"),
        ],
        "stairs": [
            {"x": 347, "y": 662, "w": 438, "h": 258, "steps": (500, 662, 785, 920), "dir": "v", "spacing": 41,
             "to": "etage", "label": "Escalier ↑ étage (salles 7–8)", "lx": 470, "ly": 640},
        ],
        "fixtures": [],
    },
}

DEFAULT_LEVEL = "etage"
ZONE_LEVEL = {key: level for level, plan in LEVELS.items() for key, *_ in plan["zones"]}
ZONE_CHOICES = [(k, k) for k in ZONE_LEVEL]
DEFAULT_USAGE = {"1": "SANIT", "2": "SANIT", "P3-A": "TECH",
                 **{f"P3-0{i}": "BSL3" for i in range(1, 8)}}
DEFAULT_NAME = {"P3-A": "Autoclave"}


def points(pts):
    return " ".join(f"{a},{b}" for a, b in pts)


def zones(level=DEFAULT_LEVEL):
    out = []
    for key, pts, label in LEVELS[level]["zones"]:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x, y, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        lx, ly = label or (x + w / 2, y + h / 2)
        bw = min(w - 8, 150)
        out.append({"key": key, "points": points(pts), "x": x, "y": y, "w": w, "h": h,
                    "bx": round(lx - bw / 2), "by": round(ly - 45), "bw": bw, "small": h < 90 or w < 100})
    return out


def stair_lines(s, spacing=13):
    x1, y1, x2, y2 = s["steps"]
    spacing = s.get("spacing", spacing)
    if s.get("dir") == "v":
        return [(x, y1, x, y2) for x in range(x1, x2 + 1, spacing)]
    return [(x1, y, x2, y) for y in range(y1, y2 + 1, spacing)]
