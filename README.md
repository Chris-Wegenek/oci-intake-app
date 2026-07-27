# OCI Intake Application

Full-stack local app for uploading an Oracle Cloud Infrastructure inventory workbook or cloud bill export, reviewing/editing the normalized rows, selecting an OCI flexible compute shape, approving the data, and mapping the specs to OCI rate-card SKUs.

## Run

```bash
/Users/gus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 app.py
```

Then open `http://127.0.0.1:8787`.

The first screen lets you choose `On-prem inventory` for server/application spreadsheets or `Cloud bill` for AWS, Azure, and GCP bill exports. Cloud bill mode accepts PDF, CSV, TSV, XLSX, and XLS files.

## OpenAI mode

OpenAI is used in exactly two workflow areas:

1. **Inventory scrub:** the upload endpoint uses the Responses API with a strict JSON schema to identify the inventory table and map messy source columns into the fixed Review columns: Application Name, Machine Name, Environment, OCPUs, RAM, Storage, and Hours Running. Deterministic validation checks row counts, required fields, units, and mixed MiB/GB populations before accepting the AI result.
2. **Architecture plan:** the architecture endpoint asks OpenAI for a constrained OCI landing-zone plan. Deterministic code keeps all quantities and user region/AD/DR choices authoritative, renders the draw.io and PNG files, validates the XML and image pixels, and includes the plan plus QA report in the architecture ZIP.

Pricing, cloud-bill mapping, Review edits, and all BOM math remain deterministic. OpenAI never writes rates, totals, or raw draw.io XML.

Both assists use the lower-cost `gpt-5-mini` model with low reasoning effort by default. If OpenAI is unavailable, upload and architecture generation continue with validated deterministic fallbacks.

```bash
OPENAI_API_KEY=... OPENAI_MODEL=gpt-5-mini OPENAI_UPLOAD_MODEL=gpt-5-mini OPENAI_BILL_MODEL=gpt-5-mini OPENAI_ARCHITECTURE_MODEL=gpt-5-mini /Users/gus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 app.py
```

For local development, copy `.env.example` to `.env.local` and put your real key there. `.env.local` is intentionally ignored by Git.

## Vercel deployment

This repo includes `vercel.json`, `api/index.py`, and `requirements.txt` so Vercel can run the Python backend as a serverless function.

In Vercel, add these environment variables before deploying:

- `OPENAI_API_KEY`: your OpenAI API key
- `OPENAI_API_ENABLED`: optional; set to `false` to temporarily disconnect OpenAI calls
- `OPENAI_MODEL`: optional shared fallback, defaults to `gpt-5-mini`
- `OPENAI_UPLOAD_MODEL`: optional, defaults to `gpt-5-mini`
- `OPENAI_UPLOAD_REASONING_EFFORT`: optional, defaults to `low`
- `OPENAI_BILL_MODEL`: optional unresolved cloud-bill mapper, defaults to `gpt-5-mini`
- `OPENAI_BILL_REASONING_EFFORT`: optional, defaults to `low`
- `OPENAI_ARCHITECTURE_MODEL`: optional, defaults to `gpt-5-mini`
- `OPENAI_ARCHITECTURE_REASONING_EFFORT`: optional, defaults to `low`

Do not commit the real API key to GitHub. The app reads it from Vercel at runtime.

## Rate cards

- Shape choices: `E4 Standard`, `E5 Standard`, `E6 Standard Ax`, `X9 Standard`, and `X12 Standard Ax`
- `B112530`: E6 Standard Ax OCPU-hour rate, `OCPU x 730`
- `B112531`: E6 Standard Ax Memory GB-hour rate, `GB x 730`
- `X9-OCPU`: X9 Standard OCPU-hour rate, `OCPU x 730`
- `X9-MEMORY`: X9 Standard Memory GB-hour rate, `GB x 730`
- `X12AX-OCPU`: X12 Standard Ax OCPU-hour rate, `OCPU x 730`
- `X12AX-MEMORY`: X12 Standard Ax Memory GB-hour rate, `GB x 730`
- `B91961`: Block volume GB-month rate
- `B89057`: File storage GB-month rate

The app applies the user-provided conversion of `2 vCPU = 1 OCPU`.
