# raf-batch-api-examples

Idiomatic Python example for bulk RAF (Risk Adjustment Factor) scoring via the RAF
**Batch** API. **Verified live 2026-06-01** — the request/response samples below are
actual.

The batch API is a **3-step job** (not a single JSON POST):

```
1) POST  /raf-batch-api/<scoreType>        multipart: risk_model, risk_factor, file=CSV  -> raf_batch_id
2) GET   /raf-batch-api/check-status/<id>  poll until status == "Completed"              -> download_url
3) GET   /raf-batch-api/download/<id>      -> a short-lived (~120s) signed AWS S3 URL to a .zip
4) GET   <signed S3 url>                   -> .zip containing an .xlsx of scored members
```

Auth on every call: header **`ApiKey: <key>`** plus an empty `X-CSRF-TOKEN:`
(NOT `Authorization: Bearer`).

## Get a Batch API key

https://www.rafscorecalculator.com/raf-score-batch — read from `RAF_BATCH_API_KEY`.
**Never hardcode your key.**

## Quickstart

```bash
pip install -r requirements.txt
export RAF_BATCH_API_KEY=your_batch_api_key_here
python batch_submit.py
```

This uploads `data/input_pre_prospective.csv`, polls until complete, fetches the signed
S3 URL, and downloads the result `.zip` into `out/`.

## Input CSV (real schema)

One row **per (member, diagnosis)** — members are grouped by `ID`. The repo ships the
three official sample CSVs in `data/` (downloaded from the docs links below).

| Score type | Submit endpoint | Sample CSV | `Flag` values |
|---|---|---|---|
| Pre-Prospective | `getPreProspectScore` | [input_pre_prospective.csv](https://www.vbcriskanalytics.com/input_pre_prospective.csv) | `Last_Year` \| `Current_Year` |
| Post-Prospective | `getPostProspectScore` | [input_post_prospective.csv](https://www.vbcriskanalytics.com/input_post_prospective.csv) | `New` \| `Billed` \| `Missed` |
| Post-Concurrent | `getPostCncntScore` | [input_post_concurrent.csv](https://www.vbcriskanalytics.com/input_post_concurrent.csv) | `No_Changes` \| `Deletion` \| `Addition` (+ `Modification_To`) |

```csv
ID,Gender,Age,ICD-10 CM Code,Flag
1,Male,65,E1122,Last_Year
1,Male,65,J449,Current_Year
2,Male,84,E1142,Last_Year
3,Female,72,N186,Current_Year
```

Columns: `ID` (numeric, your de-identified member id), `Gender` (`Male`/`Female`),
`Age` (≤ 125), `ICD-10 CM Code`, `Flag` (per table above).

## Real request / response (verified)

**Step 1 — submit** (`out/batch_submit_response.json`):

```bash
curl -X POST 'https://www.vbcriskanalytics.com/raf-batch-api/getPreProspectScore' \
  -H 'accept: */*' -H "ApiKey: $RAF_BATCH_API_KEY" -H 'X-CSRF-TOKEN: ' \
  -F 'risk_model=CMS-HCC-V28 Continuing Enrollee' \
  -F 'risk_factor=Community NonDual Aged' \
  -F 'file=@data/input_pre_prospective.csv;type=text/csv'
```
```json
{ "code": 201, "raf_batch_id": 3400, "status": "Queued",
  "message": "Info: File is queued for processing.",
  "check_status_url": "https://www.vbcriskanalytics.com/raf-batch-api/check-status/3400" }
```

**Step 2 — status** walks `Queued`(201) → `Running`(202) → `Completed`(200):
```json
{ "code": 200, "raf_batch_id": 3400, "status": "Completed", "available hits": 598002,
  "message": "Info: File processing completed.",
  "download_url": "https://www.vbcriskanalytics.com/raf-batch-api/download/3400" }
```
`available hits` is your remaining quota (decrements by members scored).

**Step 3 — signed S3 URL** (fetch within ~120s, no `ApiKey` header):
```json
{ "download_url": "https://web-portal-npi-data.s3.amazonaws.com/raf-batch-process/.../06012026063153_O.zip?X-Amz-…&X-Amz-Expires=120&X-Amz-Signature=…",
  "status": "Completed" }
```

> ⚠️ **Observed (trial key, 2026-06-01):** the result `.zip`'s inner `.xlsx` came back
> **0 bytes** even though `status` was `Completed` and hits were consumed. The job flow and
> S3 delivery are correct; an empty payload looks like a trial-tier limitation — retry
> later or check account limits.

## Errors

`401`/`415` invalid key · `412` risk model required · `413` risk factor required ·
`414` file required · `418` invalid gender · `419` age > 125 · `420` columns missing ·
`425` invalid risk model · `426` invalid risk factor · `427` only CSV allowed ·
`429` invalid flag · `430` license/limit. Verified 401: `{"code":401,"message":"Error: Invalid API Key"}`.

## Learn more

See the [HCC RAF scoring guide](https://www.rafscorecalculator.com/hcc-raf?utm_source=github&utm_medium=referral&utm_campaign=rsc-lb-2026&utm_content=p24)
for background on how diagnoses roll up into a risk score.

For a plain-language primer on [what a RAF score is](https://www.rafscorecalculator.com/what-is-raf-score?utm_source=github&utm_medium=referral&utm_campaign=rsc-lb-2026&utm_content=p24)
before you batch-score members, start here.

---

Maintained by VBC Risk Analytics. Not coding/billing/clinical advice; verify against the
current CMS Rate Announcement. Synthetic data only — no PHI.
