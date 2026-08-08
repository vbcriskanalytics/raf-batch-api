"""Runnable example: bulk RAF scoring via the RAF Batch API (VERIFIED flow).

Walks the real 4-step batch job:
  1. POST a CSV to /raf-batch-api/getPreProspectScore (multipart) -> raf_batch_id
  2. poll /check-status/<id> until status == "Completed"
  3. GET /download/<id> -> a signed AWS S3 URL (expires ~120s)
  4. download the .zip (containing an .xlsx of scored members)

Usage:
    export RAF_BATCH_API_KEY=your_batch_api_key_here
    python batch_submit.py

Reads data/input_pre_prospective.csv (the real sample CSV from the docs:
columns ID,Gender,Age,ICD-10 CM Code,Flag). All data is SYNTHETIC — no PHI.
"""

import json
import os
import sys

from raf_batch_client import (
    API_KEY_ENV_VAR,
    SIGNUP_URL,
    RafBatchClient,
    RafBatchClientError,
)

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(HERE, "data", "input_pre_prospective.csv")
OUTPUT_DIR = os.path.join(HERE, "out")

RISK_MODEL = "CMS-HCC-V28 Continuing Enrollee"
RISK_FACTOR = "Community NonDual Aged"
SCORE_TYPE = "pre-prospect"


def main():
    if not os.environ.get(API_KEY_ENV_VAR):
        print(
            f"No Batch API key found. Set {API_KEY_ENV_VAR}, e.g.:\n"
            f"    export {API_KEY_ENV_VAR}=your_batch_api_key_here\n\n"
            f"Get a Batch API key here: {SIGNUP_URL}\n"
        )
        return 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    try:
        client = RafBatchClient()

        print(f"[1/4] Submitting {os.path.basename(INPUT_CSV)} "
              f"({RISK_MODEL} / {RISK_FACTOR}) ...")
        submitted = client.submit(INPUT_CSV, RISK_MODEL, RISK_FACTOR, SCORE_TYPE)
        print(json.dumps(submitted, indent=2))
        batch_id = submitted["raf_batch_id"]

        print(f"\n[2/4] Polling check-status/{batch_id} until Completed ...")
        status = client.wait_until_complete(batch_id)
        print(json.dumps(status, indent=2))

        print(f"\n[3/4] Getting signed download URL for {batch_id} ...")
        dl = client.get_download_url(batch_id)
        print(json.dumps(dl, indent=2))
        signed_url = dl["download_url"]

        print("\n[4/4] Downloading result .zip from S3 (expires ~120s) ...")
        out_zip = os.path.join(OUTPUT_DIR, f"batch_result_{batch_id}.zip")
        client.fetch_result(signed_url, out_zip)
        size = os.path.getsize(out_zip)
        print(f"Saved {out_zip} ({size} bytes)")
        if size < 300:
            print("NOTE: result archive is unusually small — on trial keys the "
                  "inner .xlsx can come back empty even when status=Completed. "
                  "Retry later or check your account limits.")
    except (RafBatchClientError, KeyError) as exc:
        print(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
