"""Find which company slugs actually exist on Greenhouse / Lever / Ashby, so the watchlist is real, not guessed."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import httpx
from . import UA

# Candidates: AI/ML-heavy companies, remote-first employers, and Nepal/South-Asia hiring firms. Wrong guesses are simply dropped.
CANDIDATES = """anthropic openai cohere mistral huggingface scaleai databricks perplexity characterai runwayml elevenlabs stability stabilityai together togetherai
fireworks fireworksai anyscale modal replicate wandb langchain llamaindex pinecone weaviate qdrant chroma deepl glean sierra harvey hebbia writer jasper synthesia
descript notion ramp brex mercury stripe vercel supabase posthog retool airtable figma linear zapier gitlab hashicorp datadog snowflake elastic mongodb confluent
dbtlabs fivetran airbyte dagster prefect samsara wise grammarly canva miro discord reddit instacart doordash lyft coinbase robinhood plaid chime deel remote oyster
rippling gusto lattice toptal turing andela crossover mercor invisible snorkelai labelbox appen surgeai cerebras groq sambanova nvidia deepmind inflection adept
cognition replit codeium sourcegraph tabnine anysphere poolside magic imbue reka ai21 nousresearch liquid lamini predibase clarifai h2oai datarobot dataiku tecton
hopsworks comet neptune arize truera fiddler galileo honeyhive langfuse helicone braintrust humanloop vellum cresta assemblyai deepgram speechmatics rev otter krisp
veed lightricks pika luma midjourney ideogram leonardo photoroom gamma fusemachines leapfrog cotiviti verisk f1soft deerwalk javra automattic toggl buffer doist
mozilla duckduckgo kaggle weightsandbiases scale cresta cleanlab unstructured vectara contextual lightning lightningai modular mosaicml activeloop zilliz milvus
dust lindy adept-ai thinkingmachines safesuperintelligence xai""".split()

ATS_URL = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{}/jobs",
    "lever": "https://api.lever.co/v0/postings/{}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{}",
}


def _check(args):
    ats, slug = args
    try:
        r = httpx.get(ATS_URL[ats].format(slug), headers=UA, timeout=15, follow_redirects=True)
        if r.status_code != 200:
            return None
        d = r.json()
        n = len(d.get("jobs", [])) if isinstance(d, dict) else len(d)
        return (ats, slug, n)
    except Exception:
        return None


def probe(candidates=None, workers: int = 16, min_jobs: int = 1) -> dict[str, list[str]]:
    cands = sorted(set(candidates or CANDIDATES))
    work = [(a, s) for s in cands for a in ATS_URL]
    found: dict[str, list[str]] = {a: [] for a in ATS_URL}
    with ThreadPoolExecutor(workers) as ex:
        for res in ex.map(_check, work):
            if res and res[2] >= min_jobs:
                found[res[0]].append(res[1])
    return {a: sorted(v) for a, v in found.items()}
