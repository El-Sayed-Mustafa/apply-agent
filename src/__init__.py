"""حزمة الوكيل."""
import sys

# الطباعة بالعربي والإيموجي بتفشل على كونسول ويندوز الافتراضي
# (cp1256). ده مش تجميل: `src.harvest` مات على أول `print` قبل ما
# يعمل أي شغل، والتشغيلة كلها ضاعت على حاجة مالهاش علاقة بالمنطق.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

