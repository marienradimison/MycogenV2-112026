"""QuantiFERON-TB Gold Plus (ELISA) : courbe standard, contrôle qualité et conversion DO → UI/mL.

Reproduit le calcul du logiciel d'analyse QFT-Plus (fiche « Résultats QuantiFERON®-TB Gold Plus ») :
    - courbe : régression linéaire de ln(DO moyenne) sur ln(concentration) des standards S1 à S3 ;
    - concentration d'un échantillon : exp((ln(DO) − ordonnée à l'origine) / pente) ;
    - DO non numérique (ex. « OVER », « > 4 ») : 4,000 attribuée (note #) ;
    - résultat > 10 UI/mL : affiché « > 10 » (hors de l'intervalle linéaire, note ¶).

Critères de validité du test ELISA (notice QFT-Plus) :
    S1 : DO moyenne ≥ 0,600 et CV ≤ 15 % ; S2 : CV ≤ 15 % ; S3 et S4 : chaque réplicat à ± 0,040 de la moyenne ;
    S4 (standard zéro) : DO moyenne ≤ 0,150 ; coefficient de corrélation ≥ 0,98.
"""
import math
import re
import statistics
from decimal import ROUND_HALF_UP, Decimal

STANDARDS = [("S1", Decimal("4.00")), ("S2", Decimal("1.00")), ("S3", Decimal("0.25")), ("S4", Decimal("0.00"))]
OVER_OD = Decimal("4.000")
LINEAR_MAX = Decimal("10")


def parse_od(raw):
    """(DO, non numérique ?) ; « 0,248 » → 0.248 ; texte non numérique → 4,000."""
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        return None, False
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return Decimal(text), False
    return OVER_OD, True


def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Curve:
    """Courbe standard d'une plaque (DO des standards en double)."""

    def __init__(self, ods):
        # ods : {"S1": (DO1, DO2), …}
        self.rows = []
        for name, conc in STANDARDS:
            values = [v for v in ods.get(name, ()) if v is not None]
            mean = sum(values) / len(values) if values else None
            cv = None
            if len(values) == 2 and mean and name in ("S1", "S2"):
                cv = Decimal(statistics.stdev([float(v) for v in values]) / float(mean) * 100)
            self.rows.append({"name": name, "conc": conc, "values": values, "mean": mean, "cv": cv})
        self.slope = self.intercept = self.r = None
        points = [(math.log(float(r["conc"])), math.log(float(r["mean"])))
                  for r in self.rows[:3] if r["mean"] and r["mean"] > 0]
        if len(points) >= 2:
            xs, ys = zip(*points)
            mx, my = statistics.fmean(xs), statistics.fmean(ys)
            sxx = sum((x - mx) ** 2 for x in xs)
            sxy = sum((x - mx) * (y - my) for x, y in points)
            syy = sum((y - my) ** 2 for y in ys)
            if sxx:
                self.slope = sxy / sxx
                self.intercept = my - self.slope * mx
                self.r = sxy / math.sqrt(sxx * syy) if syy else 1.0
        self.qc()

    def qc(self):
        for r in self.rows:
            ok, mean, values = True, r["mean"], r["values"]
            if mean is None or len(values) < 2:
                ok = False
            elif r["name"] == "S1":
                ok = mean >= Decimal("0.600") and (r["cv"] is None or r["cv"] <= 15)
            elif r["name"] == "S2":
                ok = r["cv"] is None or r["cv"] <= 15
            else:
                ok = all(abs(v - mean) <= Decimal("0.040") for v in values)
                if r["name"] == "S4":
                    ok = ok and mean <= Decimal("0.150")
            r["ok"] = ok
        self.r_ok = self.r is not None and self.r >= 0.98
        self.valid = self.slope is not None and self.r_ok and all(r["ok"] for r in self.rows)

    def concentration(self, od):
        """DO → UI/mL (Decimal, 2 décimales) ; None si la courbe n'est pas calculable."""
        if od is None or self.slope is None:
            return None
        if od <= 0:
            return Decimal("0.00")
        return q2(math.exp((math.log(float(od)) - self.intercept) / self.slope))


def capped(value):
    return min(value, LINEAR_MAX) if value is not None else None


def display_iu(value, flag=""):
    """« 0,86 », « > 10 » (au-delà de l'intervalle linéaire)."""
    if value is None:
        return "—"
    if value > LINEAR_MAX:
        return "> 10" + flag
    return f"{q2(value):.2f}".replace(".", ",") + flag


def sheet_rows(q):
    """Valeurs de la fiche pour un résultat QFT : UI/mL, différences, notes # et ¶."""
    over = set((q.od_over or "").split(",")) - {""}
    out_range = False

    def val(name, value):
        nonlocal out_range
        flag = "#" if name in over else ""
        if value is not None and value > LINEAR_MAX:
            out_range = True
        return display_iu(value, flag)

    def diff(value):
        nonlocal out_range
        if value is None or q.nil is None:
            return "—"
        if value > LINEAR_MAX:
            out_range = True
            return "> 10¶"
        return display_iu(value - q.nil)

    row = {
        "nil": val("nil", q.nil), "tb1": val("tb1", q.tb1), "tb2": val("tb2", q.tb2),
        "mitogen": val("mitogen", q.mitogen),
        "tb1_nil": diff(q.tb1), "tb2_nil": diff(q.tb2), "mitogen_nil": diff(q.mitogen),
    }
    row["over_note"] = bool(over)
    row["range_note"] = out_range
    return row
