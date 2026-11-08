"""
اختبارات الرقيب.

كل اختبار هنا عطل حقيقي حصل وفضل ساكت — الرقيب لازم يقوله.
"""
import json
from datetime import datetime, timedelta, timezone

from src import audit

NOW = datetime(2026, 10, 24, 8, 0, tzinfo=timezone.utc)


def run(component, hours_ago=1, status="ok", seen=5, new=1, **detail):
    return {"component": component,
            "started_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "status": status, "items_seen": seen, "items_new": new,
            "detail": detail}


def full_day(**over):
    rows = [run(c) for c in audit.DAILY] + [run("discover", hours_ago=2)]
    return rows + list(over.get("extra", []))


def texts(items):
    return " | ".join(t for _, t in items)


def test_a_healthy_day_has_no_findings():
    assert audit.runs(full_day(), NOW) == []


def test_a_step_that_never_logged_is_reported():
    rows = [r for r in full_day() if r["component"] != "notify"]
    assert "الإرسال" in texts(audit.runs(rows, NOW))


def test_a_failed_step_is_red_with_its_reason():
    rows = full_day(extra=[run("harvest", status="failed", error="مفيش جلسة LinkedIn")])
    found = audit.runs(rows, NOW)
    assert any(lvl == audit.RED and "مفيش جلسة LinkedIn" in t for lvl, t in found)


def test_comments_returning_zero_for_days_is_reported():
    """صفر منشور كل يوم من 6 أكتوبر، ومحدش عرف."""
    rows = [r for r in full_day() if r["component"] != "comment"]
    rows += [run("comment", hours_ago=h, seen=0, new=0) for h in (72, 48, 1)]
    assert "الكومنتات: صفر منشور 3" in texts(audit.runs(rows, NOW))


def test_two_comment_zeros_are_not_yet_a_pattern():
    rows = [r for r in full_day() if r["component"] != "comment"]
    rows += [run("comment", hours_ago=h, seen=0, new=0) for h in (48, 1)]
    assert "الكومنتات" not in texts(audit.runs(rows, NOW))


def test_job_board_with_no_cards_twice_means_the_page_changed():
    rows = [r for r in full_day() if r["component"] != "jobboard"]
    rows += [run("jobboard", hours_ago=h, seen=0, new=0) for h in (24, 1)]
    found = audit.runs(rows, NOW)
    assert any(lvl == audit.RED and "لوحة الوظايف: صفر كروت" in t for lvl, t in found)


def test_linkedin_objection_is_red():
    rows = full_day(extra=[run("engage", status="failed",
                               error="اعتراض: الصفحة بتقول: unusual activity")])
    found = audit.runs(rows, NOW)
    assert found[0][0] == audit.RED or any(
        lvl == audit.RED and "لينكدإن اعترض" in t for lvl, t in found)


def test_scoring_with_nothing_scored_points_at_the_quota():
    rows = [r for r in full_day() if r["component"] != "score"]
    rows.append(run("score", scored=0, failed=12))
    assert "حصة Gemini" in texts(audit.runs(rows, NOW))


def test_github_poller_that_never_finishes_is_reported():
    """التشغيلات بتقف عند العشر دقايق، فمبتسجّلش discover أبدًا."""
    rows = [r for r in full_day() if r["component"] != "discover"]
    rows.append(run("discover", hours_ago=30))
    assert "GitHub" in texts(audit.runs(rows, NOW))


class _Raising:
    def __init__(self, msg):
        self.msg = msg

    def table(self, _):
        return self

    def select(self, *a, **k):
        return self

    def limit(self, _):
        return self

    def execute(self):
        raise RuntimeError(self.msg)


def test_supabase_egress_restriction_is_named_plainly():
    """23 أكتوبر: كل خطوة بقت بترجع 402 والسبب مكانش باين."""
    db = _Raising("{'code': 402, 'details': 'restricted: exceed_egress_quota'}")
    found = audit.database(db)
    assert found and found[0][0] == audit.RED and "نقل البيانات" in found[0][1]


def test_check_stops_at_a_dead_database(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "ENGAGE_STATE", tmp_path / "none.json")
    db = _Raising("connection refused")
    found = audit.check(db, NOW)
    assert len(found) == 1 and "الداتابيز مش بترد" in found[0][1]


def test_follow_that_does_not_match_the_company_is_flagged(tmp_path, monkeypatch):
    """حادثة mossconstruct."""
    p = tmp_path / "engage.json"
    at = (NOW - timedelta(hours=1)).isoformat()
    p.write_text(json.dumps({"companies": {
        "moss": {"at": at, "slug": "mossconstruct", "followed": True,
                 "url": "https://www.linkedin.com/company/mossconstruct/"},
        "snoonu": {"at": at, "slug": "snoonu", "followed": True},
        "careem": {"at": at, "slug": "careem-networks", "followed": True},
    }}), encoding="utf-8")
    monkeypatch.setattr(audit, "ENGAGE_STATE", p)
    found = texts(audit.follows(NOW))
    # "moss" بتطابق mossconstruct بالحروف — ده اللي خدع الكود. الرقيب
    # بيقارن كلمات كاملة، فبيمسكها، ومبيعملش إنذار كاذب على المطابق.
    assert "moss" in found
    assert "snoonu" not in found and "careem" not in found


def test_follow_with_no_shared_word_is_flagged(tmp_path, monkeypatch):
    p = tmp_path / "engage.json"
    at = (NOW - timedelta(hours=1)).isoformat()
    p.write_text(json.dumps({"companies": {
        "precursory": {"at": at, "slug": "acme-builders", "followed": True},
    }}), encoding="utf-8")
    monkeypatch.setattr(audit, "ENGAGE_STATE", p)
    assert "precursory" in texts(audit.follows(NOW))


def test_render_says_so_when_all_is_well():
    assert audit.render([]) == "🛡 الرقيب: مفيش ملاحظات."


def test_report_still_goes_out_when_the_watchdog_breaks(tmp_path, monkeypatch):
    """الرقيب عمره ما يمنع التقرير نفسه."""
    from src import report
    p = tmp_path / "daily-report.txt"
    p.write_text("تقرير", encoding="utf-8")
    monkeypatch.setattr(report, "PATH", p)
    monkeypatch.setattr(report.audit, "check",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    sent = []
    monkeypatch.setattr(report.telegram, "send", lambda t, *a, **k: sent.append(t))
    assert report.main() == 0
    assert sent and sent[0].startswith("تقرير") and "الرقيب ما اشتغلش" in sent[0]
    assert not p.exists()


def test_old_style_follow_entries_do_not_break_the_watchdog(tmp_path, monkeypatch):
    """ملف الحالة الحقيقي فيه سجلات قديمة كانت تاريخ بس — وقّعت الرقيب."""
    p = tmp_path / "engage.json"
    p.write_text(json.dumps({"companies": {"old co": "2026-09-30"}}), encoding="utf-8")
    monkeypatch.setattr(audit, "ENGAGE_STATE", p)
    assert audit.follows(NOW) == []


def test_glued_slugs_of_the_real_company_are_not_flagged():
    """أول تشغيل حقيقي للرقيب طلّع الاتنين دول غلط — وهما صح."""
    assert audit.same_company("cntxt ai", "cntxtai")
    assert audit.same_company("siemens digital industries software", "siemenssoftware")
    assert not audit.same_company("moss", "mossconstruct")
    assert not audit.same_company("precursory", "acme-builders")
