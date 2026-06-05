# OCI Intake Application

Full-stack local app for uploading an Oracle Cloud Infrastructure inventory workbook or cloud bill export, reviewing/editing the normalized rows, selecting an OCI flexible compute shape, approving the data, and mapping the specs to OCI rate-card SKUs.

## Run

```bash
/Users/gus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 app.py
```

Then open `http://127.0.0.1:8787`.

The first screen lets you choose `On-prem inventory` for server/application spreadsheets or `Cloud bill` for AWS, Azure, and GCP bill exports. Cloud bill mode accepts PDF, CSV, TSV, XLSX, and XLS files.

## LLM mode

The upload endpoint uses the OpenAI Responses API when `OPENAI_API_KEY` is present to inspect workbook sheets, identify the inventory table, and map messy spreadsheet columns into the app's canonical server/application fields. If the LLM call is unavailable, upload falls back to the original rule-based workbook parser.

Upload normalization also understands JSON-in-cell columns such as AWS `tags`. The LLM can map tag keys like `Name`, `appId`, `environment`, and `os` into the preview table instead of treating the full JSON string as one field.

The review table also includes an AI edit box. It calls `/api/edit-table` with the current rows and applies the returned changes, approval updates, or new rows before pricing.

Cloud bill upload uses service-aware parsing plus an additional LLM mapping pass after parsing. It groups repeated bill-line patterns, compares them against Oracle's cross-cloud service mapping guidance and cloud price-list metering rules, applies deterministic OCI target mappings first, and writes the inferred OCI service/product and review confidence back to the editable table.

By default, the cloud-bill LLM pass sends sanitized service/meter pattern summaries only. It does not send filenames, account labels, source costs, row tags, or row-level billing details unless `OPENAI_BILL_INCLUDE_PRIVATE_CONTEXT=true` is explicitly set.

The pricing endpoint always performs deterministic SKU math from the supplied rate card so the app is testable locally. If `OPENAI_API_KEY` is present, `/api/price` also calls the OpenAI Responses API to validate/enrich the SKU mapping. Set `OPENAI_UPLOAD_MODEL`, `OPENAI_BILL_MODEL`, `OPENAI_BILL_REASONING_EFFORT`, `OPENAI_TABLE_EDIT_MODEL`, and `OPENAI_PRICING_MODEL` to tune the upload-cleaning, cloud-bill mapping, table-editing, and pricing-review calls independently. `OPENAI_MODEL` remains a shared fallback.

```bash
OPENAI_API_KEY=... OPENAI_UPLOAD_MODEL=gpt-5.5 OPENAI_BILL_MODEL=gpt-5.5 OPENAI_BILL_REASONING_EFFORT=xhigh OPENAI_TABLE_EDIT_MODEL=gpt-5.5 OPENAI_PRICING_MODEL=gpt-5.5 /Users/gus/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 app.py
```

For local development, copy `.env.example` to `.env.local` and put your real key there. `.env.local` is intentionally ignored by Git.

## Vercel deployment

This repo includes `vercel.json`, `api/index.py`, and `requirements.txt` so Vercel can run the Python backend as a serverless function.

In Vercel, add these environment variables before deploying:

- `OPENAI_API_KEY`: your OpenAI API key
- `OPENAI_UPLOAD_MODEL`: optional, defaults to `gpt-5.5`
- `OPENAI_BILL_MODEL`: optional, defaults to `gpt-5.5`
- `OPENAI_BILL_REASONING_EFFORT`: optional, defaults to `xhigh` for the cloud-bill mapping pass
- `OPENAI_BILL_INCLUDE_PRIVATE_CONTEXT`: optional, defaults to `false`; keep this off unless you want the cloud-bill mapping prompt to include richer row context
- `OPENAI_TABLE_EDIT_MODEL`: optional, defaults to `gpt-5.5`
- `OPENAI_PRICING_MODEL`: optional, defaults to `gpt-5.5`
- `OPENAI_MODEL`: optional shared fallback when a specific model variable is not set

Do not commit the real API key to GitHub. The app reads it from Vercel at runtime.

## Rate cards

- Shape choices: `E4 Standard`, `E5 Standard`, and `E6 Standard Ax`
- `B112530`: E6 Standard Ax OCPU-hour rate, `OCPU x 730`
- `B112531`: E6 Standard Ax Memory GB-hour rate, `GB x 730`
- `B91961`: Block volume GB-month rate
- `B89057`: File storage GB-month rate

The app applies the user-provided conversion of `2 vCPU = 1 OCPU`.
