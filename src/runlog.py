"""
سجل التشغيلات للخطوات اللي مكانتش بتسجّل.

التقييم والإرسال والكومنتات والمتابعة بيكتبوا في agent_runs من زمان.
لوحة الوظايف والمنشورات ومتابعة الشركات لأ — يعني لو وقعوا أو رجعوا
صفر أيام ورا بعض، مفيش أثر غير في مخرجات الطرفية اللي محدش بيقراها.
الرقيب (`audit`) بيقرا الجدول ده، فاللي مش متسجّل مش بيتراقب.
"""
from __future__ import annotations

from datetime import datetime, timezone


def log(component: str, started: datetime, result: dict,
        seen: int = 0, new: int = 0) -> None:
    """سجّل نتيجة تشغيلة. السجل عمره ما يوقّع الخطوة نفسها."""
    status = "failed" if result.get("error") else "ok"
    try:
        from .main import get_client
        get_client().table("agent_runs").insert({
            "component": component,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "items_seen": int(seen or 0),
            "items_new": int(new or 0),
            "detail": {k: v for k, v in result.items()
                       if isinstance(v, (str, int, float, bool, type(None)))},
        }).execute()
    except (Exception, SystemExit) as exc:   # get_client بيعمل sys.exit
        print(f"(تحذير: مقدرتش أسجّل التشغيلة — {exc})")
