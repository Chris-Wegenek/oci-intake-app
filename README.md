# OCI Intake Application

Full-stack local app for uploading an Oracle Cloud Infrastructure inventory workbook, reviewing/editing the normalized rows, selecting an OCI flexible compute shape, approving the data, and mapping the specs to OCI rate-card SKUs.

## Run

```bash
/Users/gus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 app.py
```

Then open `http://127.0.0.1:8787`.

## LLM mode

The upload endpoint uses the OpenAI Responses API when `OPENAI_API_KEY` is present to inspect workbook sheets, identify the inventory table, and map messy spreadsheet columns into the app's canonical server/application fields. If the LLM call is unavailable, upload falls back to the original rule-based workbook parser.

The pricing endpoint always performs deterministic SKU math from the supplied rate card so the app is testable locally. If `OPENAI_API_KEY` is present, `/api/price` also calls the OpenAI Responses API to validate/enrich the SKU mapping. Set `OPENAI_MODEL` to override the default model.

```bash
OPENAI_API_KEY=... OPENAI_MODEL=gpt-4o-mini /Users/gus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 app.py
```

For local development, copy `.env.example` to `.env.local` and put your real key there. `.env.local` is intentionally ignored by Git.

## Vercel deployment

This repo includes `vercel.json`, `api/index.py`, and `requirements.txt` so Vercel can run the Python backend as a serverless function.

In Vercel, add these environment variables before deploying:

- `OPENAI_API_KEY`: your OpenAI API key
- `OPENAI_MODEL`: optional, defaults to `gpt-4.1-mini`

Do not commit the real API key to GitHub. The app reads it from Vercel at runtime.

## Rate cards

- Shape choices: `E4 Standard`, `E5 Standard`, and `E6 Standard Ax`
- `B97384`: OCPU-hour rate, `OCPU x 730`, varies by selected shape
- `B97385`: Memory GB-hour rate, `GB x 730`, varies by selected shape
- `B91961`: Block volume GB-month rate
- `B89057`: File storage GB-month rate

The app applies the user-provided conversion of `2 vCPU = 1 OCPU`.
