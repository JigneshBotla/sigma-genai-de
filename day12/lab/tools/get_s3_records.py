"""
Lambda Tool: get_s3_records
Called by: Recovery Agent
Action group: DataPlatformTools

Reads malformed JSON files from S3 Bronze that were written by the broken
Lambda v2 but never loaded to Snowflake.
Applies field remapping (merchant_nm → merchant_name, DD-MM-YYYY → YYYY-MM-DD).
Returns clean records ready for load_to_snowflake.

Idempotency: caller passes already_loaded_ids so this tool excludes
records already in Snowflake — zero duplicates guaranteed.
"""

import boto3, json, os, re
from datetime import datetime, timezone


def lambda_handler(event, context):
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}

    bucket             = params.get("bucket", os.getenv("SIGMA_S3_BUCKET", ""))
    prefix             = params.get("s3_prefix", "bronze/disaster/")

    raw_loaded = params.get("already_loaded_ids", "")
    already_loaded_ids = []
    if raw_loaded:
        raw_loaded_str = str(raw_loaded).strip()
        if raw_loaded_str.startswith("[") and raw_loaded_str.endswith("]"):
            try:
                already_loaded_ids = json.loads(raw_loaded_str)
            except Exception:
                already_loaded_ids = [
                    x.strip()
                    for x in raw_loaded_str.strip("[]").replace('"', '').replace("'", "").split(",")
                    if x.strip()
                ]
        else:
            already_loaded_ids = [x.strip() for x in raw_loaded_str.split(",") if x.strip()]

    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    result = read_s3_records(bucket, prefix, already_loaded_ids, region)

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "function":    event.get("function"),
            "functionResponse": {
                "responseBody": {"TEXT": {"body": json.dumps(result, default=str)}}
            },
        },
    }


def fix_record(record: dict) -> dict:
    """Apply field remapping from the broken Lambda v2."""
    fixed = dict(record)

    # Fix field rename: merchant_nm → merchant_name
    if "merchant_nm" in fixed and "merchant_name" not in fixed:
        fixed["merchant_name"] = fixed.pop("merchant_nm")

    # Fix date format: DD-MM-YYYY → YYYY-MM-DD
    date_val = fixed.get("transaction_date", "")
    if re.match(r"^\d{2}-\d{2}-\d{4}$", str(date_val)):
        parts = str(date_val).split("-")
        fixed["transaction_date"] = f"{parts[2]}-{parts[1]}-{parts[0]}"

    return fixed


def read_s3_records(bucket: str, prefix: str, already_loaded_ids: list,
                    region: str) -> dict:
    if not bucket:
        return {"error": "SIGMA_S3_BUCKET not set in environment"}

    s3 = boto3.client("s3", region_name=region)

    if not prefix or not prefix.startswith("bronze/"):
        prefix = "bronze/disaster/"

    resp  = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    files = [
        o["Key"] for o in resp.get("Contents", [])
        if o["Key"].endswith(".json") and o["Size"] > 0
    ]

    loaded_set         = set(already_loaded_ids)
    raw_records        = []
    fixed_records      = []
    quarantine_records = []
    skipped_ids        = []

    for key in files:
        try:
            body    = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            content = json.loads(body)
            batch   = content if isinstance(content, list) else [content]

            for rec in batch:
                raw_records.append(rec)
                fixed = fix_record(rec)
                tid   = fixed.get("transaction_id", "")

                if tid and tid in loaded_set:
                    skipped_ids.append(tid)
                elif not tid or float(fixed.get("amount", 0) or 0) <= 0:
                    quarantine_records.append(fixed)
                else:
                    fixed_records.append(fixed)
                    if tid:
                        loaded_set.add(tid)
        except Exception:
            pass

    # Write clean records to S3 staging — agents pass S3 references, not data.
    # load_to_snowflake reads from this key directly (avoids 170KB blob in context).
    ts_str      = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    staging_key = f"bronze/staging/recovery_{ts_str}.json"
    q_key       = None

    try:
        s3.put_object(
            Bucket=bucket, Key=staging_key,
            Body=json.dumps(fixed_records, default=str).encode(),
            ContentType="application/json",
        )
    except Exception as e:
        staging_key = f"ERROR writing staging: {e}"

    if quarantine_records:
        q_key = f"bronze/quarantine/recovery_{ts_str}.json"
        try:
            s3.put_object(
                Bucket=bucket, Key=q_key,
                Body=json.dumps(quarantine_records, default=str).encode(),
                ContentType="application/json",
            )
        except Exception:
            q_key = None

    return {
        "bucket":              bucket,
        "s3_prefix":           prefix,
        "files_read":          len(files),
        "raw_records_found":   len(raw_records),
        "duplicates_skipped":  len(skipped_ids),
        "clean_records":       len(fixed_records),
        "quarantined_records": len(quarantine_records),
        "s3_staging_key":      staging_key,
        "quarantine_key":      q_key,
        "field_fixes_applied": {
            "merchant_nm_renamed": sum(1 for r in raw_records if "merchant_nm" in r),
            "date_format_fixed":   sum(
                1 for r in raw_records
                if re.match(r"^\d{2}-\d{2}-\d{4}$", str(r.get("transaction_date", "")))
            ),
        },
        "next_step": (
            f"Call load_to_snowflake with s3_staging_key='{staging_key}' "
            f"and bucket='{bucket}' to load {len(fixed_records)} clean records."
        ),
    }



# ── Local test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()

    bucket = os.getenv("SIGMA_S3_BUCKET", "")
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

    print(f"\nReading disaster files from s3://{bucket}/bronze/disaster/...\n")
    result = read_s3_records(bucket, "bronze/disaster/", [], region)

    print(f"Files read         : {result['files_read']}")
    print(f"Raw records found  : {result['raw_records_found']}")
    print(f"Duplicates skipped : {result['duplicates_skipped']}")
    print(f"Clean records      : {result['clean_records']}")
    print(f"Field fixes        : {result['field_fixes_applied']}")

    if result["records"]:
        print(f"\nSample (after fix): {json.dumps(result['records'][0], indent=2)}")

    if "--test" in sys.argv:
        assert "records" in result
        print("\nget_s3_records.py test PASSED")
