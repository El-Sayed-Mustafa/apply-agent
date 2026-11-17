"""
مواقع التوظيف اللي بتتقري من كروم بتاعك: Wuzzuf و Bayt و GulfTalent
و Indeed و Naukrigulf و Wellfound.

  python -m src.sitejobs --urls                  صفحات البحث (JSON) للتشغيلة اليومية
  python -m src.sitejobs --ingest state/sitejobs.json   فلترة وحفظ اللي اتقرا

ليه كروم بتاعك ومش متصفح البرنامج (17-18 نوفمبر): الأربعة الأولانيين
بيوقفوا المتصفح الأوتوماتيك عند "Just a moment" حتى وإنت مسجل دخول،
و Naukrigulf عدّاه مرة ورفضه في التانية (ERR_HTTP2_PROTOCOL_ERROR).
كروم بتاعك بيعدّي لوحده. مفيش تخطّي لأي تحقق: لو صفحة طلبت إثبات إنك
إنسان، الموقع ده بيتساب اليوم ده.

الشغل نفسه في التشغيلة اليومية (Claude بكروم): يفتح كل صفحة، يشغّل
src/sitejobs.js، ويكتب النتايج في state/sitejobs.json. الملف ده بيحوّلها
لوظايف، وبيعدّيها على الاستهداف، وبيحفظ اللي عدّى في نفس جدول jobs —
فبتمشي نفس الطريق: تقييم → تليجرام بزرار «قدّم».
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .adapters import Job

# صفحة أو اتنين لكل موقع — قليل عن قصد: ده متصفحك وحسابك
SEARCHES = [
    ("wuzzuf", "https://wuzzuf.net/search/jobs/?q=ai%20engineer&sort=1"),
    ("wuzzuf", "https://wuzzuf.net/search/jobs/?q=machine%20learning&sort=1"),
    ("bayt", "https://www.bayt.com/en/uae/jobs/ai-engineer-jobs/"),
    ("bayt", "https://www.bayt.com/en/saudi-arabia/jobs/ai-engineer-jobs/"),
    ("bayt", "https://www.bayt.com/en/qatar/jobs/ai-engineer-jobs/"),
    ("gulftalent", "https://www.gulftalent.com/jobs/search?search_keyword=ai%20engineer"),
    ("indeed", "https://ae.indeed.com/jobs?q=ai+engineer&sort=date"),
    ("indeed", "https://sa.indeed.com/jobs?q=ai+engineer&sort=date"),
    ("naukrigulf", "https://www.naukrigulf.com/ai-engineer-jobs"),
    ("naukrigulf", "https://www.naukrigulf.com/machine-learning-jobs"),
    ("wellfound", "https://wellfound.com/role/r/machine-learning-engineer"),
    ("wellfound", "https://wellfound.com/role/r/artificial-intelligence-engineer"),
]


NOISE = re.compile(
    r"^(\d+\s*(?:minutes?|hours?|days?|weeks?|months?)\s+ago|today|yesterday|new|"
    r"actively hiring|easy apply|full[- ]time|part[- ]time|contract|internship|"
    r"remote|hybrid|on-?site|onsite|\d+\+?\s*(?:-\s*\d+\s*)?yrs?.*|experienced.*|"
    r"\d+-\d+ employees|\$[\d,.k]+.*|save|apply|·|\d+|[\d/.-]{6,10}|"
    r"\d{1,2} [a-z]{3}(?: \d{4})?|[a-z]{3} \d{1,2}(?:, \d{4})?)$", re.I)


YEARS = re.compile(r"^\d+\s*-\s*\d+\s*years?\s*", re.I)      # Naukrigulf: "3 - 5 YearsDubai - UAE"
WF_MODE = re.compile(r"^(?:remote(?: only)?|onsite or remote|in office|hybrid|onsite)\b[^•]*•\s*(.+)$", re.I)
WF_NOISE = re.compile(r"^(?:top \d+% of responders|responds within .*|\d+ years? of exp.*|no equity|"
                      r".*\d(?:\.\d+)?\s*[k%]\s*[–-].*)$", re.I)   # مرتب بأي عملة أو أسهم: "د.إ60k – د.إ100k"، "1.0% – 2.0%"


def _lines(card: str, title: str) -> list[str]:
    out = []
    # GulfTalent بيفصل بـTab، وBayt بـ" | "
    for raw in re.split(r"[\n\t|]", card or ""):
        line = YEARS.sub("", raw.strip(" \t·•|")).strip()
        if not line or line == title or NOISE.match(line) or WF_NOISE.match(line):
            continue
        out.append(line)
    return out


COUNTRY_SLUGS = {"uae": "UAE", "saudi-arabia": "Saudi Arabia", "ksa": "Saudi Arabia",
                 "qatar": "Qatar", "kuwait": "Kuwait", "bahrain": "Bahrain", "oman": "Oman",
                 "egypt": "Egypt", "ae": "UAE", "sa": "Saudi Arabia", "qa": "Qatar"}


def _url_country(site: str, url: str) -> str:
    """البلد من لينك الوظيفة نفسه لما الكارت مايقولش (bayt /en/uae/، indeed ae.، wuzzuf = مصر)."""
    if site == "wuzzuf":
        return "Egypt"
    m = re.match(r"https?://([a-z]{2})\.indeed\.com", url)
    if m:
        return COUNTRY_SLUGS.get(m.group(1), "")
    m = re.search(r"(?:bayt\.com/(?:en|ar)|gulftalent\.com)/([a-z-]+)/jobs/", url)
    return COUNTRY_SLUGS.get(m.group(1), "") if m else ""


def _parse(item: dict) -> tuple[str, str]:
    from . import targeting
    company, location = _parse_card(item)
    hint = _url_country(item.get("site") or "", item.get("url") or "")
    if hint and not (location and targeting.detect_country(location)[0]):
        location = f"{location}, {hint}" if location else hint
    return company, location[:120]


def _parse_card(item: dict) -> tuple[str, str]:
    """(الشركة، المكان) من نص الكارت لما الموقع ماادّاهمش منفصلين."""
    from . import targeting
    company = (item.get("company") or "").strip()
    location = (item.get("location") or "").strip()
    title = (item.get("title") or "").strip()
    lines = _lines(item.get("card") or "", title)
    site = item["site"]

    def place(cands):
        # سطر قصير فيه بلد — مش ملخص الوظيفة
        return next((l for l in cands if len(l) < 60 and not l.lower().startswith("summary")
                     and targeting.detect_country(l)[0]), "")

    if site == "wuzzuf" and lines and " - " in lines[0]:
        # "Confidential - Cairo, Egypt"
        c, l = lines[0].split(" - ", 1)
        return company or c.strip(), location or l.strip()
    if site == "wellfound":
        # الشركة فوق في راس الكارت (والإضافة بتبعتها)، والمكان في "Remote only • India"
        mode = next((m for m in map(WF_MODE.match, lines) if m), None)
        if mode and not location:
            location = mode.group(1).strip()
        if not company and lines and not WF_MODE.match(lines[0]):
            company = lines[0]
        return company[:120], location[:120]
    if site == "bayt" and lines:
        # "Title | Company | Summary: ..."
        company = company or lines[0]
        return company[:120], (location or place(lines[1:]))[:120]
    if not location:
        location = place(lines)
    if not company:
        company = next((l for l in lines if l != location and len(l) < 80
                        and not targeting.detect_country(l)[0]), "")
    return company[:120], location[:120]


def _remote(card: str, location: str) -> str:
    t = f"{card} {location}".lower()
    if re.search(r"\bremote\b|work from home|عن بعد", t):
        return "remote"
    if re.search(r"\bhybrid\b", t):
        return "hybrid"
    return "onsite" if location else "unknown"


def to_job(item: dict) -> Job | None:
    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    if not title or not url.startswith("http"):
        return None
    company, location = _parse(item)
    return Job(
        company_name=company or item["site"],
        ats=item["site"],
        external_id=url[-120:],
        title=title[:160],
        location=location or None,
        remote_type=_remote(item.get("card") or "", location),
        # كارت البحث بس — التقييم بيشتغل بيه، والتفاصيل في صفحة الوظيفة
        description=re.sub(r"\n{2,}", "\n", item.get("card") or "")[:3000],
        url=url,
        posted_at=datetime.now(timezone.utc).isoformat(),
    )


class _Row:
    def __init__(self, j: Job):
        self.title, self.location = j.title, j.location
        self.remote_type, self.description = j.remote_type, j.description


def ingest(path: str, dry: bool = False) -> dict:
    """اقرا ملف النتايج، فلتر بالاستهداف، احفظ الجديد."""
    return ingest_pages(json.loads(Path(path).read_text(encoding="utf-8")), dry)


LOG = Path("state/sitejobs-log.jsonl")


def ingest_pages(pages, dry: bool = False, quiet: bool = False) -> dict:
    """
    صفحة أو أكتر من القارئ (extension/sitejobs.js): فلتر وحفظ.
    الإضافة بتبعت هنا عن طريق المساعد (src/helper.py → /sitejobs).
    """
    from . import targeting
    if isinstance(pages, dict):
        pages = [pages]
    stats: dict[str, dict] = {}
    keep: list[Job] = []
    seen = set()
    for page in pages:
        site = page.get("site") or "?"
        s = stats.setdefault(site, {"read": 0, "kept": 0, "blocked": 0})
        if page.get("blocked"):
            s["blocked"] += 1
        for item in page.get("jobs") or []:
            item.setdefault("site", site)
            j = to_job(item)
            if not j or j.url in seen:
                continue
            seen.add(j.url)
            s["read"] += 1
            if targeting.evaluate(_Row(j)).eligible:
                s["kept"] += 1
                keep.append(j)
    saved = []
    if keep and not dry:
        from .main import get_client, save
        saved = save(get_client(), keep)
    result = {"pages": len(pages), "kept": len(keep), "saved": len(saved), "sites": stats,
              "new": [{"site": j.ats, "title": j.title, "company": j.company_name,
                       "location": j.location} for j in saved[:20]]}
    if not dry:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                                "page": pages[0].get("page") if pages else "",
                                **{k: result[k] for k in ("kept", "saved", "sites")}},
                               ensure_ascii=False) + "\n")
    if not quiet:
        for site, s in stats.items():
            note = f" · ⚠ {s['blocked']} صفحة طلبت تحقق (اتسابت)" if s["blocked"] else ""
            print(f"   {site:<11} اتقرا {s['read']:>3} · مناسب {s['kept']:>3}{note}")
        print(f"\n📊 {sum(s['read'] for s in stats.values())} وظيفة · "
              f"{len(keep)} عدّوا الاستهداف · {len(saved)} جديدة")
        for j in saved[:12]:
            print(f"   · {j.ats:<10} {j.title[:45]:<47} {j.company_name[:20]:<22} {j.location or '—'}")
    return result


def status(since_hours: float = 24) -> dict:
    """اللي الإضافة بعتته في آخر N ساعة — للتشغيلة اليومية والرقيب."""
    from datetime import timedelta
    cut = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    per: dict[str, dict] = {}
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("at", "") < cut:
                continue
            for site, s in (rec.get("sites") or {}).items():
                p = per.setdefault(site, {"pages": 0, "read": 0, "kept": 0, "blocked": 0})
                p["pages"] += 1
                for k in ("read", "kept", "blocked"):
                    p[k] += s.get(k, 0)
            per.setdefault("_saved", {"n": 0})["n"] += rec.get("saved", 0)
    return per


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", action="store_true")
    ap.add_argument("--ingest")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.urls:
        for s, u in SEARCHES:
            print(u)
        return 0
    if a.status:
        per = status()
        saved = per.pop("_saved", {"n": 0})["n"]
        if not per:
            print("مفيش صفحات وصلت من الإضافة في آخر 24 ساعة.")
            return 0
        for site in sorted(per):
            p = per[site]
            note = f" · ⚠ {p['blocked']} صفحة طلبت تحقق" if p["blocked"] else ""
            print(f"   {site:<11} {p['pages']} صفحة · اتقرا {p['read']} · مناسب {p['kept']}{note}")
        print(f"\n📊 جديد اتحفظ: {saved}")
        missing = sorted({s for s, _ in SEARCHES} - set(per))
        if missing:
            print("⚠ ماوصلش حاجة من: " + "، ".join(missing))
        return 0
    if a.ingest:
        from dotenv import load_dotenv
        load_dotenv()
        from . import runlog
        started = datetime.now(timezone.utc)
        r = ingest(a.ingest, a.dry_run)
        if not a.dry_run:
            blocked = sum(s["blocked"] for s in r["sites"].values())
            runlog.log("sitejobs", started,
                       {"pages": r["pages"], "kept": r["kept"], "saved": r["saved"],
                        "blocked_pages": blocked,
                        "sites": ",".join(f"{k}:{v['read']}" for k, v in r["sites"].items())},
                       seen=r["kept"], new=r["saved"])
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
