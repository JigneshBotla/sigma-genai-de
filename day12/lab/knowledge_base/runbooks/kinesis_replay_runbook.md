# Runbook — S3 Bronze Replay with Idempotent Recovery

**Use when:** Records are in S3 Bronze but did not load to Snowflake.
**Do NOT use:** If S3 files are missing or zero-byte (different failure mode).

## Pre-conditions
1. Root cause must be identified and fixed BEFORE replay.
   Replaying into a broken pipeline re-introduces the problem.
2. The Lambda LIVE alias must point to the stable version.
   Confirm: `aws lambda get-alias --function-name sigma-data-producer --name LIVE`

## Steps

### Step 1 — Determine the exact failure window
Use the Forensics Agent output: `anomaly_window.detected_at`
This is the timestamp when Lambda v2 was deployed and started writing bad files.

### Step 2 — Get already-loaded transaction IDs
```sql
SELECT transaction_id
FROM SIGMA.SILVER.TRANSACTIONS
WHERE _loaded_at >= '[failure_start_timestamp]'
```
Pass this list to get_s3_records as `already_loaded_ids`.

### Step 3 — Read records from S3 Bronze
Call `get_s3_records` with:
- `s3_prefix`: "bronze/disaster/" (where Lambda v2 wrote the malformed files)
- `already_loaded_ids`: list from step 2

The tool reads all JSON files, applies field remapping, and returns clean records.
Field fixes applied automatically:
- `merchant_nm` → `merchant_name`
- Date format: `DD-MM-YYYY` → `YYYY-MM-DD`

### Step 4 — Quality gate before loading
Split records:
- Clean: transaction_id not null, amount > 0, transaction_date matches YYYY-MM-DD
- Quarantine: any record that fails

### Step 5 — Load clean records
Call `load_to_snowflake` with the clean records.
The MERGE INTO on transaction_id provides a second layer of deduplication.

### Step 6 — Verify
```sql
SELECT COUNT(*) FROM SIGMA.SILVER.TRANSACTIONS
WHERE _loaded_at >= '[recovery_start_timestamp]'
```
Must match the `rows_loaded` count returned by load_to_snowflake.

## S3 File Retention
S3 files in `bronze/disaster/` are retained indefinitely.
Recovery can be run at any time after the failure is detected.

## Idempotency Guarantee
Two mechanisms protect against duplicates:
1. `already_loaded_ids` filters at the S3 read step
2. `MERGE INTO ON transaction_id` at the Snowflake write step
Running this recovery twice produces zero duplicate rows.
