"""
جدول تكرار المهارات — من غير أي AI.

بحث نصي بقاموس مرادفات. مجاني، فوري، وحتمي.
ده الـ baseline اللي أي حل بالـ LLM لازم يثبت إنه أحسن منه.
"""
import io
import json
import re
import sys
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, "spike")
from importlib import import_module
_m = import_module("04_skills") if False else None

# القاموس: الاسم الموحّد ← كل الصيغ اللي ممكن تتكتب بيها
SKILLS = {
    "Python":            [r"python"],
    "SQL":               [r"\bsql\b"],
    "TypeScript":        [r"typescript", r"\bts\b"],
    "JavaScript":        [r"javascript", r"\bjs\b"],
    "Go":                [r"\bgolang\b", r"\bgo\b(?! to| for| through)"],
    "Rust":              [r"\brust\b"],
    "C++":               [r"c\+\+"],
    "Java":              [r"\bjava\b(?!script)"],
    "Bash/Shell":        [r"\bbash\b", r"shell scripting"],

    "PostgreSQL":        [r"postgres", r"\bpsql\b"],
    "BigQuery":          [r"bigquery"],
    "Snowflake":         [r"snowflake"],
    "Redis":             [r"\bredis\b"],
    "Kafka":             [r"\bkafka\b"],
    "Spark":             [r"apache spark", r"\bspark\b"],
    "Airflow":           [r"airflow"],
    "dbt":               [r"\bdbt\b"],
    "ETL/ELT pipelines": [r"\betl\b", r"\belt\b", r"data pipeline"],
    "Data warehousing":  [r"data warehous", r"warehouse"],

    "LLM / GenAI":       [r"\bllm", r"large language model", r"generative ai",
                          r"\bgpt\b", r"foundation model"],
    "RAG":               [r"\brag\b", r"retrieval[- ]augmented"],
    "Vector databases":  [r"vector (?:db|database|store|search)", r"pinecone",
                          r"weaviate", r"pgvector", r"embedding"],
    "Prompt engineering":[r"prompt engineer", r"prompting"],
    "Fine-tuning":       [r"fine[- ]tun"],
    "PyTorch":           [r"pytorch", r"torch"],
    "TensorFlow":        [r"tensorflow"],
    "Machine learning":  [r"machine learning", r"\bml\b"],
    "Deep learning":     [r"deep learning", r"neural network"],
    "NLP":               [r"\bnlp\b", r"natural language process"],
    "Speech/Audio ML":   [r"\btts\b", r"\basr\b", r"speech", r"text[- ]to[- ]speech",
                          r"voice (?:ai|model|clon)", r"audio (?:ml|model)"],
    "MLOps":             [r"mlops", r"model (?:serving|deployment)"],
    "AI agents":         [r"\bagentic\b", r"ai agent", r"\bagents?\b(?= framework)"],

    "REST APIs":         [r"\brest\b", r"restful", r"\bapis?\b"],
    "GraphQL":           [r"graphql"],
    "Webhooks":          [r"webhook"],
    "Microservices":     [r"microservice"],
    "Distributed systems":[r"distributed system"],
    "System design":     [r"system design", r"architect"],

    "Docker":            [r"docker", r"container"],
    "Kubernetes":        [r"kubernetes", r"\bk8s\b"],
    "AWS":               [r"\baws\b", r"amazon web services"],
    "GCP":               [r"\bgcp\b", r"google cloud"],
    "Azure":             [r"\bazure\b"],
    "Terraform":         [r"terraform"],
    "CI/CD":             [r"ci/cd", r"continuous (?:integration|deployment)",
                          r"github actions"],
    "Linux":             [r"\blinux\b", r"\bunix\b"],
    "Observability":     [r"observability", r"monitoring", r"datadog", r"grafana"],

    "React":             [r"\breact\b"],
    "Next.js":           [r"next\.js", r"nextjs"],
    "Node.js":           [r"node\.js", r"nodejs"],
    "Frontend":          [r"front[- ]?end"],
    "Backend":           [r"back[- ]?end"],

    "Workflow automation":[r"\bn8n\b", r"zapier", r"workflow automation"],
    "Web scraping":      [r"scraping", r"crawler", r"crawling"],
    "Testing":           [r"unit test", r"integration test", r"\btesting\b"],
    "Git":               [r"\bgit\b", r"version control"],
    "Analytics/BI":      [r"tableau", r"looker", r"power bi", r"dashboards?"],
    "Statistics":        [r"statistic", r"probabilit"],
    "Security":          [r"security", r"vulnerabilit", r"threat"],
}


def main() -> None:
    jobs = json.load(open("spike/real_jobs.json", encoding="utf-8"))

    # نفس تجميع الوظايف المتشابهة — من غيره الأرقام كذب
    def shingles(t):
        w = re.findall(r"[a-z0-9+#./]+", t.lower())
        return {" ".join(w[i:i + 5]) for i in range(max(len(w) - 4, 1))}

    reps, uniq = [], []
    for j in jobs:
        sh = shingles(j["description"])
        if any(len(sh & r) / len(sh | r) >= 0.80 for r in reps):
            continue
        reps.append(sh)
        uniq.append(j)

    n = len(uniq)
    print(f"{len(jobs)} إعلان  →  {n} وظيفة فريدة\n")

    counts = Counter()
    where = defaultdict(list)
    for j in uniq:
        text = j["description"]
        for name, pats in SKILLS.items():
            if any(re.search(p, text, re.I) for p in pats):
                counts[name] += 1
                where[name].append(j["title"])

    print("=" * 70)
    print(f"{'المهارة':<24}{'وظايف':>7}{'%':>6}   ")
    print("-" * 70)
    for name, c in counts.most_common(40):
        pct = c / n * 100
        print(f"{name:<24}{c:>7}{pct:>5.0f}%   {'#' * round(pct / 4)}")

    missing = [s for s in SKILLS if s not in counts]
    if missing:
        print(f"\nمظهرتش خالص ({len(missing)}): {', '.join(missing)}")

    json.dump({"unique_jobs": n, "counts": dict(counts)},
              open("spike/baseline.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n[saved] spike/baseline.json")


if __name__ == "__main__":
    main()
