# Data Quality & Governance Copilot

## 1. Project in one sentence

This project is a human-in-the-loop data quality application that detects problems in tabular data, uses Groq to explain the detected evidence, and applies changes only after a reviewer approves them.

## 2. Problem it solves

Real-world datasets commonly contain:

- Duplicate customers with spelling variations.
- Names written in different scripts.
- Invalid emails and phone numbers.
- Missing values.
- Mixed date formats.
- City spelling and whitespace inconsistencies.
- No clear record of who approved a data change.

The Copilot produces a quality report, identifies probable duplicate records, proposes safe fixes, and creates a cleaned copy without changing the original upload.

## 3. Core design principle

**Code detects. Groq explains. A human approves. The audit trail records everything.**

The LLM does not decide whether two records are duplicates. That decision comes from deterministic rules and similarity scoring. The LLM only converts the computed evidence into plain English.

## 4. End-to-end flow

```text
Upload CSV/Parquet
        |
        v
Infer schema
        |
        v
Profile quality and detect issues
        |
        v
Standardize a working copy
        |
        v
Block and score probable duplicates
        |
        v
Mask personal data
        |
        v
Groq explains evidence and proposes a structured action
        |
        v
Human approves, rejects, or edits the proposal
        |
        v
Apply approved changes to a NEW cleaned file
        |
        v
Show health improvement and audit history
```

## 5. Main components

### `core.py`

The deterministic data quality engine. It provides:

- Schema inference for ID, name, email, phone, date, city, numeric, and text fields.
- Completeness, validity, uniqueness, and consistency profiling.
- Invalid email and phone detection.
- Ambiguous-date detection.
- Phone normalization to the last ten digits.
- Date normalization to ISO format.
- Text cleanup and Indic-script transliteration.
- Duplicate blocking and weighted similarity scoring.
- Health score calculation.
- Safe application of approved decisions.

### `explainer.py`

The Groq/OpenAI-compatible LLM layer. It:

- Receives masked values and computed evidence only.
- Uses `GROQ_API_KEY`, `GROQ_BASE_URL`, and `GROQ_MODEL`.
- Validates the response using Pydantic.
- Allows only `merge_records`, `standardize_value`, or `flag_for_review`.
- Retries invalid JSON once.
- Uses a deterministic template fallback if the key is missing or the call fails.

### `app.py`

The Streamlit user interface for upload, schema review, quality scanning, human review, and CSV download.

### `api.py`

The FastAPI backend exposing upload, profiling, matching, explanation, decisions, apply, health, audit, and export endpoints.

### `tests/`

Tests cover normalization, profiling, duplicate matching, fallback explanations, and PII masking.

## 6. Duplicate matching logic

The application first creates candidate pairs through blocking. Two records become candidates when they share a normalized phone, normalized date, or transliterated phonetic name key.

Candidate pairs are then scored using:

```text
name  = 30%
dob   = 25%
phone = 25%
email = 15%
city  = 5%
```

Confidence bands:

- High: score is at least 0.95.
- Review: score is between 0.75 and 0.95.
- Ignore: score is below 0.75.

The score shown to the reviewer always comes from the Python matcher, never from the LLM.

## 7. Health score

The health score combines:

```text
25% completeness
25% validity
20% uniqueness
20% consistency
10% timeliness placeholder
```

The application shows the score before and after approved changes so the reviewer can see whether quality improved.

## 8. How to configure Groq

```powershell
Copy-Item .env.example .env
```

Add the supplied key to `.env`:

```env
GROQ_API_KEY=your_key_here
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=llama-3.3-70b-versatile
```

The key must not be committed to Git or pasted into Python files.

## 9. How to run

```powershell
uv venv .venv
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
streamlit run app.py
```

Optional API server:

```powershell
uvicorn api:app --reload
```

Run tests:

```powershell
pytest -p no:cacheprovider tests -q
```

## 10. Ready-to-read presentation script

### Opening

“Good morning. My project is the Data Quality and Governance Copilot. It is designed to solve a common problem in analytics projects: data is often available, but it is not reliable enough to use directly.

This tool accepts a messy CSV or Parquet file, profiles the data, detects invalid values and probable duplicates, explains the evidence using a Groq-hosted language model, and creates a cleaned copy only after a human reviewer approves the changes.”

### Explain the design

“The most important design decision is the separation of responsibilities. Python code performs detection and similarity scoring. Groq does not make the matching decision; it only explains the already-computed evidence. The reviewer remains in control of every change, and the original file is never overwritten.”

### Start the application

“I will start the Streamlit application with `streamlit run app.py`. The application opens with an upload screen. I will use `example_data.csv`, which contains duplicate Rajesh records, mixed dates, a missing email, invalid emails, inconsistent phone numbers, a city typo, and an Indic-script name and city.”

### Upload and schema review

“After upload, the application infers the semantic type of every column. For example, it recognizes `email` as an email field, `phone` as a phone field, and `dob` as a date field. The reviewer can override any inferred type before scanning.”

### Run the quality scan

“When I select Run quality scan, the profiler checks completeness, validity, uniqueness, consistency, and duplicate rows. Invalid phone numbers, malformed emails, missing values, and ambiguous dates are added to the issue list. The dashboard also displays the initial health score.”

### Explain matching

“The matcher does not compare every record with every other record. It first blocks records that share a normalized phone, date, or phonetic name key. It then calculates a weighted score using name, date of birth, phone, email, and city similarity.

For example, Rajesh Kumar and Rajesh Kumaar share a phone number, date, and email. Their score is high, so they appear in the review queue as a possible duplicate cluster.”

### Explain Groq’s role

“The structured evidence is sent to Groq only after masking personal values. The model receives masked values such as `R***r` and computed field scores, rather than the raw customer information.

Groq returns a JSON explanation containing a summary, reasoning, proposed action, confidence, and risk. The response is validated against a Pydantic schema and an allowed-action list. If the model returns invalid output twice, the system uses a deterministic template explanation instead.”

### Human review

“The reviewer now sees the explanation, confidence band, risk, and evidence. The reviewer can approve, reject, or edit the proposal. This is the human governance gate. No proposal is automatically applied simply because the model suggested it.”

### Apply and export

“After approval, the system creates a new cleaned CSV. It preserves the original upload and applies only approved fixes. For a merge, the more complete row becomes the survivor and missing fields can be filled from the duplicate row.

The application then recalculates the health score and displays the before-and-after result. It also keeps an audit record containing the proposal, reviewer decision, timestamp, and resulting action.”

### Close

“This project demonstrates a practical and safe AI pattern for data quality: deterministic code handles accuracy-sensitive detection, the LLM improves explanation, and a human controls the final change. This makes the workflow more transparent, safer for personal data, and easier to audit than an automatic cleaning script.”

## 11. Short viva answers

**Why is an LLM used?**  
To explain structured evidence in plain English and propose a reviewable action. It is not used as the matcher.

**Why is the original file not modified?**  
To preserve source immutability and allow rollback or comparison.

**How is privacy handled?**  
Personal values are masked before the LLM request, and raw values are not included in the prompt.

**What happens when the LLM fails?**  
The response is retried once. If it still fails validation, the deterministic template fallback is used.

**Can the LLM automatically merge records?**  
No. Every change requires a reviewer decision.

**How can it scale?**  
The blocking step reduces pairwise comparisons. The same profiling and matching logic can later be moved to PySpark for larger datasets.
