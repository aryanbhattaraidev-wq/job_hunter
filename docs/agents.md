# Agent diagram

The system is a **deterministic pipeline** with AI "agents" called as bounded, validated functions at the steps
that need judgement. No agent can submit an application: only the human-approved `submit` path can.

```mermaid
flowchart TB
    subgraph SRC["Discovery agent (no LLM)"]
        direction LR
        S1["Free APIs & feeds<br/>RemoteOK, Remotive, Arbeitnow,<br/>WeWorkRemotely, HN Who's Hiring"]
        S2["Company boards<br/>Greenhouse / Lever / Ashby<br/>(~100 probed slugs)"]
        S3["Alert emails<br/>LinkedIn / Indeed / Glassdoor<br/>via Gmail API (no scraping)"]
    end

    SRC --> NORM["Normalize + dedupe<br/>(fingerprint company|title|location)"]
    NORM --> PRE["Prefilter agent (rules)<br/>role - seniority - paid - location<br/>region-locked remote - clearance"]
    PRE -- rejected --> DROP[("rejected<br/>with reason")]
    PRE --> SCORE["Scoring agent (rules)<br/>role + skill overlap + seniority + keywords<br/>explainable 0-100"]

    SCORE --> RERANK["Re-rank agent (Gemini, free)<br/>realistic fit, hidden years,<br/>paid?, eligible for Nepal?"]
    RERANK --> NOTIFY["Notifier<br/>Telegram + Gmail digest"]
    NOTIFY --> USER{{"You"}}

    USER -- "pick a job" --> PREP

    subgraph PREP["prepare_application"]
        direction TB
        CV["CV tailor agent<br/>SELECT real facts - VALIDATE ids/skills<br/>RENDER LaTeX - COMPILE PDF<br/>reports skill gaps"]
        BRIEF["Company brief agent<br/>from posting text only"]
        COVER["Cover-letter agent<br/>(smart model, capped)<br/>cites fact IDs, numbers and tech<br/>verified in code, 2 retries"]
        FILL["Form-filler agent (Playwright + Edge)<br/>fills what the profile grounds<br/>NEVER submits"]
        CV --> FILL
        BRIEF --> COVER --> FILL
    end

    FILL --> Q[("applications table<br/>status = pending")]
    Q --> REVIEW["Review (CLI or UI)<br/>screenshot, every field, letter,<br/>fields that need you"]
    REVIEW -- approve --> HASH[("approval bound to hash of<br/>CV + letter + every field")]
    REVIEW -- reject --> Q
    HASH --> SUBMIT["submit.py - the ONLY submit path<br/>re-check hash - re-fill form<br/>must reproduce same snapshot<br/>final y/N confirmation"]
    SUBMIT --> SENT(["Application sent<br/>proof screenshot saved"])

    PROFILE[("Master profile<br/>facts with stable IDs")] -.grounds.-> CV
    PROFILE -.grounds.-> COVER
    PROFILE -.grounds.-> FILL
    PROFILE -.compared to.-> RERANK

    classDef ai fill:#e8f0fe,stroke:#4a6fd8,color:#111
    classDef human fill:#fff4d6,stroke:#c99a00,color:#111
    classDef gate fill:#fde8e8,stroke:#c0392b,color:#111
    class RERANK,CV,BRIEF,COVER,FILL ai
    class USER,REVIEW human
    class HASH,SUBMIT gate
```

## Agent roles

| Agent | Model | Input | Output | Guardrail |
|---|---|---|---|---|
| Discovery | none | source configs | raw jobs | per-source failures never abort a run; LinkedIn/Indeed/Glassdoor are not scraped |
| Prefilter | none | job + preferences | keep / reject + reason | cheap rules run before any model sees a job |
| Scoring | none | job + profile | 0-100 + breakdown | fully explainable, re-runnable |
| Re-rank | fast (Gemini, free) | profile + posting | fit, seniority, years, flags | posting wrapped as untrusted data |
| CV tailor | none (deterministic) | profile + job | LaTeX/PDF + gaps | only real fact IDs; validator rejects anything else |
| Company brief | fast | posting | brief | posting text only, lists what is unknown |
| Cover letter | smart (OpenRouter, daily cap) | facts + brief + posting | letter | cites fact IDs; numbers and technologies verified; failures retried then flagged |
| Form-filler | optional drafter | profile + live form | filled form + needs-you list | never answers EEO, visa, salary, clearance or any radio/checkbox; no submit code |
| Notifier | none | scored jobs | Telegram / email digest | marks jobs notified only if a channel succeeded |
| Submitter | none | approved application | submitted + proof | hash check, replay check, human confirmation, never called by the scheduler |

## LLM routing

```mermaid
flowchart LR
    CALL["llm.complete()"] --> Q{"smart=True and<br/>daily cap not hit?"}
    Q -- yes --> OR["OpenRouter<br/>anthropic/claude-sonnet-5.5"]
    Q -- no --> G["Gemini<br/>gemini-3.5-flash"]
    G -- "503 / 429" --> G2["backoff, then<br/>gemini-3.1-flash-lite,<br/>gemini-3.6-flash"]
    G2 -- "still failing" --> H["last resort:<br/>OpenRouter claude-haiku-5.5<br/>(counts toward cap)"]
    OR -- "error" --> G
```
