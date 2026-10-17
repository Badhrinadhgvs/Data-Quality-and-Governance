# Data Quality & Governance Copilot

A lightweight human-in-the-loop data quality application. The deterministic engine profiles data and finds likely duplicate records. An optional Groq explanation layer explains masked evidence, while a reviewer must approve changes before a new cleaned CSV is generated.

## Run locally

```powershell
uv venv .venv
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
streamlit run app.py
```

Open the **Guide to Use** page inside the app for the complete user workflow.

## Deploy with Docker

```powershell
docker build -t dq-copilot .
docker run --rm -p 8501:8501 dq-copilot
```

Or use `docker compose up --build`. The container listens on `PORT` when a hosting provider supplies it, and falls back to port `8501` locally.

## Deploy on Render

This repository includes `render.yaml`. Create a new Render Blueprint from the repository, then add `GROQ_API_KEY` as a secret environment variable if AI explanations are desired. The application works without it using the deterministic template fallback. Render's health check uses Streamlit's `/_stcore/health` endpoint.

Other suitable options are Streamlit Community Cloud (simplest for the Streamlit UI), Railway, or Hugging Face Spaces. Use the Dockerfile for providers that support Docker deployments.

## Optional API

Run the FastAPI service separately:

```powershell
uvicorn api:app --host 0.0.0.0 --port 8000
```

The API supports dataset upload, schema override, profiling, matching, explanation, reviewer decisions, apply/export, health, and audit endpoints. The included Docker image runs the Streamlit interface; deploy the API as a second web service when API access is required.

## Configuration

Copy `.env.example` to `.env` for local use. Set `GROQ_API_KEY` to enable the optional Groq explainer. `GROQ_MODEL` selects the model and `GROQ_TIMEOUT_SECONDS` bounds each request. Never commit `.env` or expose the key in source control.

The LLM receives masked values and computed field scores only. Its JSON is validated against a Pydantic schema and an allow-list. It cannot decide a match, apply a change, or bypass human review. Uploaded source data is not modified.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m py_compile app.py api.py core.py explainer.py
```
