# Project diagram

## Components

```mermaid
flowchart TB
    subgraph UI["Interfaces"]
        CLI["cli.py (Typer)<br/>run - jobs - tailor - cover<br/>prepare - review - submit - probe"]
        WEB["ui/app.py (Streamlit)<br/>7 steps: resume - preferences - sources<br/>AI - notifications - jobs - applications"]
    end

    subgraph CORE["Core (src/jobhunter)"]
        CFG["config.py<br/>preferences, sources, LLM, notify<br/>secrets in .env"]
        PROF["profile.py<br/>facts with stable IDs"]
        RI["resume_import.py<br/>PDF/text -> profile"]
        PIPE["pipeline.py<br/>discover - prefilter - score"]
        AI["ai.py<br/>re-rank - brief - cover letter<br/>+ fabrication checks"]
        CVM["cv/<br/>plan - validate - render - compile<br/>templates/cv.tex.j2"]
        LLM["llm.py<br/>Gemini - OpenRouter - Groq - Ollama<br/>fallbacks + daily cap"]
        DB["db.py (SQLite, WAL)<br/>jobs - applications - events"]
    end

    subgraph SRC["sources/"]
        ADP["adapters: RemoteOK, Remotive, Arbeitnow,<br/>WeWorkRemotely, HN, Greenhouse, Lever, Ashby, RSS"]
        PROBE["probe.py<br/>finds real company boards"]
        ALERT["alerts.py<br/>parse alert emails"]
    end

    subgraph APPLY["apply/ (human in the loop)"]
        FORM["form.py<br/>label-driven filler, no submit code"]
        PREP["__init__.py<br/>prepare_application"]
        APPR["approval.py<br/>content-hash gate"]
        SUB["submit.py<br/>only submit path"]
    end

    subgraph NOTE["notify/"]
        TG["Telegram Bot API"]
        GM["gmail.py<br/>send digest, read alerts"]
    end

    CLI --> CORE
    WEB --> CORE
    RI --> PROF
    RI --> LLM
    PIPE --> ADP
    PIPE --> DB
    PIPE --> CFG
    ADP --> ALERT
    ALERT --> GM
    AI --> LLM
    AI --> PROF
    CVM --> PROF
    PREP --> CVM
    PREP --> AI
    PREP --> FORM
    PREP --> DB
    APPR --> DB
    SUB --> APPR
    SUB --> FORM
    PIPE --> TG
    PIPE --> GM

    FORM -. "Playwright + Edge" .-> WEBSITE["Real application form<br/>(Greenhouse / Lever / Ashby)"]
    SUB -. "click submit after confirm" .-> WEBSITE
    LLM -. HTTPS .-> APIS["Gemini / OpenRouter"]
    TG -. HTTPS .-> TGAPI["Telegram"]
    GM -. OAuth .-> GAPI["Gmail API"]
```

## Data flow and storage

```mermaid
flowchart LR
    A["resume.pdf"] -->|import| P["data/profile.json"]
    C["data/config.json<br/>.env (secrets)"] --> RUN
    RUN["jobhunter run"] --> J[("data/jobhunter.db<br/>jobs: new - rejected - scored - notified<br/>tailored - applied")]
    J --> ART["data/artifacts/&lt;job id&gt;/<br/>cv.tex - cv.pdf - cover_letter.txt/.pdf<br/>prefilled.png - report.json"]
    ART --> AP[("applications<br/>pending - approved - rejected - submitted")]
    AP --> EV[("events audit log")]
    P --> ART
```

## Job lifecycle (state machine)

```mermaid
stateDiagram-v2
    [*] --> new: discovered
    new --> rejected: prefilter fails
    new --> scored: passes rules
    scored --> scored: AI re-rank adjusts score
    scored --> notified: digest sent
    notified --> tailored: you pick it
    tailored --> applied: approved + submitted
    rejected --> [*]
    applied --> [*]
```

## Application approval sequence

```mermaid
sequenceDiagram
    actor U as You
    participant P as prepare_application
    participant B as Edge (Playwright)
    participant D as SQLite
    participant S as submit.py

    U->>P: jobhunter prepare 123
    P->>P: tailor CV, write + verify cover letter
    P->>B: open real form, fill grounded fields
    B-->>P: filled list, needs-you list, screenshot
    P->>D: applications row (pending)
    U->>D: review, approve
    D-->>D: store hash(CV + letter + every field)
    U->>S: jobhunter submit 5
    S->>D: status approved? hash unchanged?
    S->>B: re-open form, re-fill
    B-->>S: snapshot
    S->>S: same snapshot as approved? else refuse
    S->>U: Submit now? (y/N)
    U-->>S: y
    S->>B: click submit
    S->>D: status submitted, proof screenshot
```

## Repository layout

```
job_hunter/
  src/jobhunter/
    cli.py  config.py  profile.py  resume_import.py  pipeline.py  ai.py  llm.py  db.py
    cv/        __init__.py  templates/cv.tex.j2
    sources/   __init__.py (adapters)  probe.py  alerts.py
    apply/     __init__.py  form.py  approval.py  submit.py
    notify/    __init__.py (Telegram, digest)  gmail.py
    ui/        app.py
  tests/       test_core.py  test_apply.py
  docs/        agents.md  architecture.md
  data/        (git-ignored) config, profile, db, artifacts, browser profile
```
