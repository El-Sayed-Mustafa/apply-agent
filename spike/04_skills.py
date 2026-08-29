"""
جدول تكرار المهارات — مع دمج المتشابه على مستويين.

  المستوى 1 · الوظايف المتشابهة  → تشابه Jaccard  (مجاني، حتمي)
  المستوى 2 · المهارات المتشابهة → قايمة مقفولة + مرادفات

البصمة الحرفية فشلت هنا: نفس الإعلان في 15 دولة بيختلف في كلمات قليلة،
فالـ hash بيطلع مختلف. الحل: نقيس نسبة التشابه بدل التطابق.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter, defaultdict

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
MODEL = os.getenv("SPIKE_MODEL", "gemini-3.6-flash")
BATCH = int(os.getenv("SPIKE_BATCH", "4"))  # وظايف في النداء الواحد — الحد المجاني 5 نداءات/دقيقة
SIMILAR = 0.80     # فوق كده = نفس الإعلان
ATTEMPTS = 5

VOCAB = [
    "Python", "SQL", "JavaScript", "TypeScript", "Go", "Rust", "Java", "C++", "Bash",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "BigQuery", "Snowflake", "Elasticsearch",
    "Spark", "Airflow", "dbt", "Kafka", "ETL/ELT pipelines", "Data modeling",
    "Data warehousing",
    "LLM APIs", "Prompt engineering", "RAG", "Vector databases", "Fine-tuning",
    "PyTorch", "TensorFlow", "Hugging Face", "Machine learning", "Deep learning",
    "NLP", "Speech/Audio ML", "MLOps", "Model evaluation", "AI agents",
    "REST APIs", "GraphQL", "Webhooks", "Microservices", "System design",
    "Distributed systems",
    "Docker", "Kubernetes", "AWS", "GCP", "Azure", "Terraform", "CI/CD", "Linux",
    "Observability",
    "React", "Next.js", "Node.js", "Frontend development", "Backend development",
    "Workflow automation", "Web scraping", "Testing", "Git", "Agile",
    "Customer-facing communication", "Technical writing", "Stakeholder management",
    "Security", "Compliance", "Analytics/BI", "Statistics", "Experimentation/AB testing",
]

_VARIANTS = {
    "PostgreSQL": ["postgres", "psql", "postgresql database"],
    "LLM APIs": ["llms", "large language models", "openai api", "anthropic api", "gpt", "llm"],
    "ETL/ELT pipelines": ["etl", "elt", "data pipelines", "pipeline development", "etl pipelines"],
    "Vector databases": ["vector db", "embeddings store", "pinecone", "weaviate", "pgvector"],
    "REST APIs": ["rest", "restful apis", "api development", "apis", "api design"],
    "CI/CD": ["continuous integration", "continuous delivery", "github actions", "jenkins"],
    "Kubernetes": ["k8s", "eks", "gke"],
    "AWS": ["amazon web services", "ec2", "s3"],
    "GCP": ["google cloud", "google cloud platform"],
    "Machine learning": ["ml", "machine-learning"],
    "Speech/Audio ML": ["tts", "asr", "speech recognition", "text to speech", "audio ml",
                        "voice ai", "audio processing", "speech synthesis"],
    "Analytics/BI": ["bi", "business intelligence", "dashboards", "tableau", "power bi", "looker"],
    "JavaScript": ["js", "es6"],
    "TypeScript": ["ts"],
    "Workflow automation": ["n8n", "zapier", "make.com", "automation tools"],
    "Data modeling": ["dimensional modeling", "schema design"],
    "Experimentation/AB testing": ["a/b testing", "ab testing", "experimentation"],
    "Customer-facing communication": ["customer facing", "client facing", "presentation skills"],
}
ALIAS: dict[str, str] = {}
for _c, _vs in _VARIANTS.items():
    for _v in _vs:
        ALIAS[_v.lower()] = _c
for _c in VOCAB:
    ALIAS.setdefault(_c.lower(), _c)

SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "skills": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "level": {"type": "string",
                                          "enum": ["required", "nice_to_have"]},
                            },
                            "required": ["name", "level"],
                        },
                    },
                },
                "required": ["index", "skills"],
            },
        }
    },
    "required": ["jobs"],
}

PROMPT = """For EACH job below, extract the technical skills and tools it requires.

Choose names from this CONTROLLED VOCABULARY whenever one fits:
{vocab}

If a genuinely distinct skill is required that is not in the list, output it as
"NEW: <short name>". Do not force a bad match. Do not invent skills absent from the text.

Mark `level`: "required" for hard requirements, "nice_to_have" for preferred/bonus.
Skip soft traits (teamwork, passion, ownership). Max 12 skills per job.
Return one entry per job, using the job's INDEX number.

{jobs}
"""


# ── المستوى 1: تشابه الوظايف ─────────────────────────────────────────────

def shingles(text: str, k: int = 5) -> set[str]:
    """قسّم النص لمجموعات كل 5 كلمات — البصمة بقت مجموعة مش رقم واحد."""
    w = re.findall(r"[a-z0-9+#./]+", text.lower())
    return {" ".join(w[i:i + k]) for i in range(max(len(w) - k + 1, 1))}


def jaccard(a: set, b: set) -> float:
    """نسبة المشترك للإجمالي. 1.0 = متطابق، 0 = مفيش أي شبه."""
    u = a | b
    return len(a & b) / len(u) if u else 0.0


def cluster(jobs: list[dict]) -> tuple[list[dict], list[list[str]]]:
    reps: list[tuple[set, dict, list[str]]] = []
    for j in jobs:
        sh = shingles(j["description"])
        for rep_sh, _, titles in reps:
            if jaccard(sh, rep_sh) >= SIMILAR:
                titles.append(j["title"])
                break
        else:
            reps.append((sh, j, [j["title"]]))
    return [r[1] for r in reps], [r[2] for r in reps]


# ── المستوى 2: تشابه المهارات ────────────────────────────────────────────

def canon(raw: str) -> tuple[str, bool]:
    s = re.sub(r"^new:\s*", "", raw.strip(), flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" .,-").lower()
    if s in ALIAS:
        return ALIAS[s], False
    for alias, target in ALIAS.items():
        if len(alias) > 4 and (s.startswith(alias + " ") or s.endswith(" " + alias)):
            return target, False
    return re.sub(r"^NEW:\s*", "", raw.strip(), flags=re.I).title(), True


def extract_batch(client, batch: list[dict]) -> dict[int, list[dict]] | None:
    blob = "\n\n".join(
        f"--- INDEX {i} ---\nTITLE: {j['title']}\n{j['description'][:3500]}"
        for i, j in enumerate(batch)
    )
    prompt = PROMPT.format(vocab="\n".join(f"- {v}" for v in VOCAB), jobs=blob)
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=SCHEMA,
    )
    for attempt in range(ATTEMPTS):
        try:
            r = client.models.generate_content(model=MODEL, contents=prompt, config=cfg)
            return {e["index"]: e["skills"] for e in json.loads(r.text)["jobs"]}
        except Exception as exc:
            msg = str(exc)
            if not any(c in msg for c in ("429", "503", "500", "UNAVAILABLE")):
                print(f"    x {msg[:100]}", flush=True)
                return None
            hint = re.search(r"retryDelay.{0,4}(\d+(?:\.\d+)?)s", msg)
            w = float(hint.group(1)) if hint else 2 ** attempt
            print(f"    ~ استنى {w:.0f}ث", flush=True)
            time.sleep(w + 0.5)
    return None


def main() -> None:
    jobs = json.load(open("spike/real_jobs.json", encoding="utf-8"))
    uniq, groups = cluster(jobs)
    # الأقرب لمجالك الأول
    PRIO = re.compile(r"(ai|ml|machine|data|research|automation|backend|"
                      r"platform|software|infrastructure|devops)", re.I)
    uniq.sort(key=lambda j: 0 if PRIO.search(j["title"]) else 1)
    limit = int(os.getenv("SPIKE_LIMIT", "0"))
    if limit:
        uniq = uniq[:limit]
    print(f"الوظايف: {len(jobs)}  →  فريدة: {len(uniq)}  "
          f"(اتشال {len(jobs) - len(uniq)} إعلان مكرر)\n", flush=True)

    big = sorted(((len(g), g[0]) for g in groups if len(g) > 1), reverse=True)
    if big:
        print("أكبر المجموعات المدمجة:", flush=True)
        for n, title in big[:5]:
            print(f"  x{n:<3} {re.sub(r' - [A-Za-z ]+$', '', title)}", flush=True)
        print(flush=True)

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    req, nice, new_terms = Counter(), Counter(), Counter()
    merged: dict[str, set[str]] = defaultdict(set)
    done = 0

    batches = [uniq[i:i + BATCH] for i in range(0, len(uniq), BATCH)]
    for bi, batch in enumerate(batches, 1):
        out = extract_batch(client, batch)
        if out is None:
            print(f"  [{bi}/{len(batches)}] فشلت", flush=True)
            continue
        for idx, skills in out.items():
            if idx >= len(batch):
                continue
            done += 1
            for s in skills:
                name, is_new = canon(s["name"])
                if is_new:
                    new_terms[name] += 1
                if s["name"].strip().lower() != name.lower():
                    merged[name].add(s["name"].strip())
                (req if s["level"] == "required" else nice)[name] += 1
        print(f"  [{bi}/{len(batches)}] {len(out)} وظايف · إجمالي {done}", flush=True)
        time.sleep(1)

    total = req + nice
    print(f"\n{'=' * 76}")
    print(f"جدول تكرار المهارات — {done} وظيفة فريدة")
    print("=" * 76)
    print(f"{'المهارة':<32}{'الكل':>6}{'أساسي':>8}{'إضافي':>8}{'% من الوظايف':>15}")
    print("-" * 76)
    for name, n in total.most_common(32):
        bar = "#" * round(n / max(done, 1) * 20)
        print(f"{name:<32}{n:>6}{req[name]:>8}{nice[name]:>8}"
              f"{n / max(done, 1) * 100:>10.0f}%  {bar}")

    print("\n【دمج المهارات المتشابهة】 صيغ مختلفة اتجمعت في اسم واحد")
    hits = [(c, v) for c, v in merged.items() if v]
    for c, variants in sorted(hits, key=lambda x: -len(x[1]))[:12]:
        print(f"  {c:<28} <- {', '.join(sorted(variants)[:6])}")
    if not hits:
        print("  (مفيش — الموديل التزم بالقايمة المقفولة تمامًا)")

    if new_terms:
        print("\n【برّه القايمة】 مرشحين يتضافوا للقاموس")
        for t, n in new_terms.most_common(15):
            print(f"  x{n:<3} {t}")

    json.dump(
        {"jobs_total": len(jobs), "jobs_unique": len(uniq), "jobs_analyzed": done,
         "required": dict(req), "nice_to_have": dict(nice),
         "merged": {k: sorted(v) for k, v in merged.items()},
         "new_terms": dict(new_terms)},
        open("spike/skills.json", "w", encoding="utf-8"),
        ensure_ascii=False, indent=2,
    )
    print("\n[saved] spike/skills.json")


if __name__ == "__main__":
    main()
