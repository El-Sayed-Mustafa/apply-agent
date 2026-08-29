import io, re, sys, time, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0"}
EP = {
 "greenhouse":"https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true",
 "lever":"https://api.lever.co/v0/postings/{t}?mode=json",
 "ashby":"https://api.ashbyhq.com/posting-api/job-board/{t}",
 "recruitee":"https://{t}.recruitee.com/api/offers/",
 "workable":"https://apply.workable.com/api/v1/widget/accounts/{t}?details=true",
}
def titles(ats, p):
    if ats in ("greenhouse","ashby","workable"): return [j.get("title","") for j in p.get("jobs",[])]
    if ats=="lever": return [j.get("text","") for j in p] if isinstance(p,list) else []
    if ats=="recruitee": return [j.get("title","") for j in p.get("offers",[])]
    return []
REL = re.compile(r"\b(ai|ml|machine learning|data|analyt|engineer|automation|backend|platform|software)\b", re.I)
CAND = [
 ("Cohere","ashby","cohere"), ("ElevenLabs","ashby","elevenlabs"),
 ("Tamara","greenhouse","tamara"), ("Careem","greenhouse","careem"),
 ("Fuse Energy","ashby","fuse"), ("HappyRobot","ashby","happyrobot.ai"),
 ("Lean Tech","ashby","LeanTech"), ("Foodics","workable","foodics"),
 ("Mozn","workable","mozn-ai"), ("Xebia APAC","greenhouse","xebiaapac"),
 ("Xebia DACH","greenhouse","xebiadach"), ("Xebia France","greenhouse","xebiafrance"),
]
print(f"{'الشركة':<14}{'النظام':<12}{'التوكن':<16}{'كل':>5}{'مناسبة':>8}")
print("-"*62)
ok=[]
for name, ats, tok in CAND:
    try:
        r = requests.get(EP[ats].format(t=tok), headers=UA, timeout=15)
        ts = titles(ats, r.json()) if r.status_code==200 else []
    except Exception as e:
        ts=[]
    rel = [t for t in ts if REL.search(t)]
    mark = "✅" if ts else "❌"
    print(f"{mark} {name:<12}{ats:<12}{tok:<16}{len(ts):>5}{len(rel):>8}")
    if ts: ok.append((name,ats,tok,len(ts),len(rel)))
    time.sleep(0.3)
print(f"\n{len(ok)} شركة شغالة")
