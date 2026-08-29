"""اسحب وظايف حقيقية وفلتر اللي في مجالك. مفيش AI هنا — مجرد جلب وفرز."""
import json, re, sys
sys.path.insert(0, ".")
from src.adapters import fetch

KEEP = re.compile(
    r"\b(ai|ml|machine learning|data|analytics|analyst|engineer|engineering|"
    r"automation|backend|platform|software|research|llm|infrastructure|devops)\b", re.I)
DROP = re.compile(
    r"\b(ios|android|mobile|swift|kotlin|frontend|front-end|designer|design|"
    r"sales|marketing|recruit|legal|finance|account executive|counsel|"
    r"communications|brand|content|people|hr|intern)\b", re.I)

jobs = fetch({"name": "ElevenLabs", "ats": "ashby", "token": "elevenlabs"})
print(f"سُحب: {len(jobs)}")

kept = [j for j in jobs if KEEP.search(j.title) and not DROP.search(j.title)]
print(f"بعد الفلترة: {len(kept)}\n")

seen, uniq = set(), []
for j in kept:
    t = re.sub(r"\s+", " ", j.title.lower()).strip()
    if t not in seen:
        seen.add(t); uniq.append(j)
print(f"عناوين فريدة: {len(uniq)}\n")
for j in uniq[:60]:
    print(f"  · {j.title}   [{j.location or '—'}]")

json.dump([{"title": j.title, "location": j.location, "url": j.url,
            "description": j.description[:6000]} for j in uniq],
          open("spike/real_jobs.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"\n[saved] spike/real_jobs.json — {len(uniq)} وظيفة")
