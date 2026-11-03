"""Veille scientifique tuberculose : sélection automatique de 3 actualités par semaine.

Sources : PubMed (articles de la semaine, revues de référence en priorité), OMS, ScienceDaily,
Google Actualités (FR). Le serveur doit avoir accès à Internet (les variables HTTP(S)_PROXY
sont respectées si l'IPM passe par un proxy).
"""
import hashlib
import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from html import unescape

from django.db import close_old_connections
from django.utils import timezone

from .models import NewsArticle

log = logging.getLogger("mycogen.news")

PER_WEEK = 3
UA = "Mycogen-LIMS/1.0 (Institut Pasteur de Madagascar)"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
GNEWS = "https://news.google.com/rss/search?"
RSS_FEEDS = [  # (source, url, filtre) — par ordre de préférence
    ("WHO", "https://www.who.int/rss-feeds/news-english.xml", "tubercul"),
    ("SCIENCEDAILY", "https://www.sciencedaily.com/rss/health_medicine/tuberculosis.xml", "tubercul"),
    ("GNEWS", GNEWS + urllib.parse.urlencode({"q": "tuberculose Madagascar", "hl": "fr", "gl": "MG", "ceid": "MG:fr"}), None),
    ("GNEWS", GNEWS + urllib.parse.urlencode({"q": "tuberculose", "hl": "fr", "gl": "FR", "ceid": "FR:fr"}), None),
    ("GNEWS", GNEWS + urllib.parse.urlencode({"q": "tuberculosis", "hl": "en-US", "gl": "US", "ceid": "US:en"}), None),
]
# Presse généraliste : seuls ces éditeurs reconnus sont retenus (Google Actualités agrège aussi des sites peu fiables)
TRUSTED_PRESS = [
    "organisation mondiale", "world health organization", "who", "oms", "institut pasteur", "inserm", "anrs",
    "médecins sans frontières", "msf", "stop tb", "unitaid", "global fund", "fonds mondial", "cdc", "cidrap",
    "le monde", "afp", "rfi", "france 24", "france info", "franceinfo", "le figaro", "libération", "la croix",
    "sciences et avenir", "science et vie", "le quotidien du médecin", "what's up doc", "medscape", "univadis",
    "egora", "pourquoi docteur", "the conversation", "reuters", "associated press", "ap news", "bbc", "the guardian",
    "stat", "nature", "science", "health policy watch", "devex", "new york times", "washington post",
    "l'express de madagascar", "midi madagasikara", "newsmada", "madagascar tribune", "2424.mg", "la vérité",
    "orange actu madagascar", "studio sifaka",
]
RSS_MAX_AGE = {"SCIENCEDAILY": 60, "WHO": 45}  # jours (21 par défaut)
# Revues privilégiées pour les articles PubMed (ordre = priorité)
TOP_JOURNALS = [
    "new england journal of medicine", "lancet", "jama", "bmj", "nature", "science", "nature medicine",
    "lancet infectious diseases", "lancet respiratory medicine", "lancet global health", "lancet microbe",
    "plos medicine", "clinical infectious diseases", "european respiratory journal",
    "american journal of respiratory and critical care medicine", "international journal of tuberculosis",
    "journal of clinical microbiology", "antimicrobial agents and chemotherapy", "eurosurveillance",
    "emerging infectious diseases", "tuberculosis (edinburgh", "nature communications", "plos pathogens",
]


def week_start(d=None):
    d = d or timezone.localdate()
    return d - timedelta(days=d.weekday())


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _clean(text):
    text = re.sub(r"<[^>]+>", " ", unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def trusted(publisher):
    p = (publisher or "").lower().strip()
    return any(p == t or p.startswith(t + " ") or p.startswith(t + ".") for t in TRUSTED_PRESS)


def journal_rank(name):
    """Rang de la revue dans TOP_JOURNALS (correspondance la plus longue), sinon en fin de liste."""
    n = re.sub(r"^the\s+", "", re.sub(r"[.:,]", " ", (name or "").lower()))
    n = re.sub(r"\s+", " ", n).strip()
    matches = [(len(j), i) for i, j in enumerate(TOP_JOURNALS) if n == j or n.startswith(j + " ")]
    return max(matches)[1] if matches else len(TOP_JOURNALS)


def fetch_pubmed(days=7):
    params = urllib.parse.urlencode({
        "db": "pubmed", "term": "tuberculosis[Title] AND hasabstract", "reldate": days, "datetype": "edat",
        "retmax": 100, "retmode": "json", "tool": "mycogen"})
    ids = json.loads(_get(f"{EUTILS}esearch.fcgi?{params}"))["esearchresult"]["idlist"]
    if not ids:
        return []
    time.sleep(0.4)  # limite NCBI : 3 requêtes / s
    params = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "json", "tool": "mycogen"})
    result = json.loads(_get(f"{EUTILS}esummary.fcgi?{params}"))["result"]
    out = []
    for pmid in result.get("uids", []):
        r = result[pmid]
        if not set(r.get("pubtype", [])) & {"Journal Article", "Review", "Randomized Controlled Trial",
                                            "Clinical Trial", "Meta-Analysis", "Systematic Review"}:
            continue
        out.append({
            "source": "PUBMED", "external_id": f"pubmed:{pmid}", "title": _clean(r.get("title")),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "publisher": r.get("fulljournalname") or r.get("source", ""),
            "published": _pubmed_date(r.get("sortpubdate") or r.get("epubdate")),
            "summary": ", ".join(a["name"] for a in r.get("authors", [])[:3]) + (" et al." if len(r.get("authors", [])) > 3 else ""),
            "rank": journal_rank(r.get("fulljournalname")),
        })
    out.sort(key=lambda a: (a["rank"], -(a["published"] or date.min).toordinal()))
    return out


def _pubmed_date(value):
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", value or "")
    return date(*map(int, m.groups())) if m else None


def fetch_rss(source, url, keyword=None):
    root = ET.fromstring(_get(url))
    out = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title"))
        desc = _clean(item.findtext("description"))
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        if keyword and keyword not in (title + " " + desc).lower():
            continue
        publisher = ""
        if source == "GNEWS":
            if " - " in title:
                title, publisher = title.rsplit(" - ", 1)
            if not trusted(publisher):
                continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate")).date()
        except (TypeError, ValueError):
            published = None
        out.append({"source": source, "external_id": f"{source.lower()}:{hashlib.sha1(link.encode()).hexdigest()}",
                    "title": title[:500], "url": link[:1000], "publisher": publisher or dict(NewsArticle.SOURCES)[source],
                    "published": published, "summary": desc[:600] if source != "GNEWS" else "", "rank": 0})
    out.sort(key=lambda a: a["published"] or date.min, reverse=True)
    return out


def refresh(force=False):
    """Complète la sélection de la semaine (3 articles). Retourne le nombre d'articles ajoutés."""
    week = week_start()
    have = NewsArticle.objects.filter(week=week).count()
    if have >= PER_WEEK and not force:
        return 0
    known = set(NewsArticle.objects.values_list("external_id", flat=True))
    today = timezone.localdate()

    pubmed, news = [], []
    try:
        pubmed = [a for a in fetch_pubmed() if a["external_id"] not in known]
    except Exception as exc:
        log.warning("PubMed indisponible : %s", exc)
    for source, url, kw in RSS_FEEDS:
        try:
            recent = today - timedelta(days=RSS_MAX_AGE.get(source, 21))
            news += [a for a in fetch_rss(source, url, kw)
                     if a["external_id"] not in known and (a["published"] is None or a["published"] >= recent)
                     and a["external_id"] not in {n["external_id"] for n in news}]
        except Exception as exc:
            log.warning("Flux %s indisponible : %s", source, exc)

    # 2 articles scientifiques + 1 actualité, complétés si une source manque
    picks = pubmed[:2] + news[:1]
    for a in pubmed[2:] + news[1:]:
        if len(picks) >= PER_WEEK:
            break
        picks.append(a)
    added = 0
    for a in picks[: max(PER_WEEK - have, 0) if not force else PER_WEEK]:
        a.pop("rank", None)
        NewsArticle.objects.get_or_create(external_id=a.pop("external_id"), defaults={**a, "week": week})
        added += 1
    log.info("Actualités : %s article(s) ajouté(s) pour la semaine du %s", added, week)
    return added


_last_attempt = {"t": 0.0}
_lock = threading.Lock()


def refresh_in_background(min_interval=6 * 3600):
    """Déclenché à l'affichage du tableau de bord ; au plus une tentative toutes les 6 h."""
    with _lock:
        if time.time() - _last_attempt["t"] < min_interval:
            return
        _last_attempt["t"] = time.time()

    def run():
        close_old_connections()
        try:
            refresh()
        except Exception:
            log.exception("Rafraîchissement des actualités impossible")
        finally:
            close_old_connections()

    threading.Thread(target=run, daemon=True, name="news-refresh").start()


def current_articles():
    week = week_start()
    items = list(NewsArticle.objects.filter(week=week)[:PER_WEEK])
    if not items:  # semaine pas encore alimentée : on garde la sélection précédente
        last = NewsArticle.objects.order_by("-week").values_list("week", flat=True).first()
        if last:
            items = list(NewsArticle.objects.filter(week=last)[:PER_WEEK])
    return items
