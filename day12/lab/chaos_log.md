# Chaos Log — Team Name: SigmaNexus

## Day 12 | Wednesday 4 June 2026

---

## Pre-Exercise Answer (fill before Phase 1)

**Question:** Should the 9 tool functions be one Lambda or separate Lambdas? What breaks if they are one?

**Your answer:**
The 9 tool functions should definitely be deployed as separate Lambdas. If all tools are bundled into a single monolithic Lambda, several critical operational and engineering issues arise:
1. **Dependency Mismatch & Package Size:** Tools like `query_snowflake` require heavy external connectors (`snowflake-connector-python`) while others like `send_sns_alert` only require light, standard Boto3 libraries. Combining them results in a bloated ZIP package, slowing down cold starts for every tool.
2. **Blast Radius & Reliability:** A runtime error, library conflict, or deployment misconfiguration in one tool function will crash the entire Lambda, disabling all 9 platform tools simultaneously.
3. **Security (Least Privilege):** Fine-grained IAM permissions cannot be easily enforced. A monolithic Lambda must have broad permissions (S3 read/write, Snowflake queries, Lambda updates, CloudWatch alarms, SNS publishes). With separate Lambdas, we limit each tool strictly to the permissions it needs.
4. **Independent Scaling & Throttling:** Different tools have different execution patterns. A high-frequency tool might throttle and block a critical recovery tool if they share the same Lambda concurrency limits.

---

## Phase 2 — Manual Investigation

*You have 60 minutes. Find the root cause before the agents do.*

**Records in Kinesis (02:00–02:20 UTC):** 80,000 records sent (estimated based on yesterday's baseline).

**Records in S3 (02:00–02:20 UTC):** 17 files, 225,647 bytes total.

**Records in Snowflake (02:00–02:20):** 0 rows loaded.

---

**Failure timestamp:** 2026-06-02T08:44:35.000+0000 UTC

**What changed at that timestamp:**
The `sigma-data-producer` Lambda was updated to Version 2 and the LIVE alias was pointed to it.

**Root cause (your hypothesis):**
Version 2 of the `sigma-data-producer` Lambda introduced silent, breaking data payload mutations:
1. It renamed the JSON key for the merchant from `merchant_name` to `merchant_nm`.
2. It altered the date format from the ISO-compliant `YYYY-MM-DD` (e.g. `2026-06-02`) to `DD-MM-YYYY` (e.g. `02-06-2026`).
Because the Snowflake database schema strictly expects `merchant_name` and the `COPY INTO` command expects `YYYY-MM-DD` formatted dates, these records failed validation checks. Since Snowflake was configured to skip errors or discard them silently rather than raising a hard exception, all incoming records were discarded, leading to a complete silent data loss.

**Why no alert fired:**
Every underlying infrastructure component (Kinesis stream, Firehose delivery stream, S3 bucket storage, and Lambda execution engines) was running perfectly from an operational standpoint, returning 200/Success status codes. Since no resource errors, memory overruns, or crashes occurred, traditional infrastructure-level monitoring remained completely green.

**Time taken to find this:** 12 minutes

---

**Signals you connected:**
1. Manually queried S3 folder `bronze/disaster/2026/06/04/02/` and saw that new files had landed with recent timestamps.
2. Inspected a raw JSON file `batch_000.json` and noticed the field name was `merchant_nm` and the date was `04-06-2026`.
3. Checked the CloudWatch Lambda configuration history for `sigma-data-producer` and found a Version 2 update at 08:44:35 UTC.

**Signal you missed (fill this in Phase 3 after seeing the agent output):**
The exact financial impact of the SLA breaches (e.g., QuickMart's SLA threshold breach of ₹50,000 due to ₹1,21,450 missing) and the exact number of rows that had null values in primary keys and would need to be quarantined.

---

## Phase 3 — Comparison

**What I found (Phase 2 manual):**
- Time taken: 12 minutes
- Root cause found? Yes
- SLA breach identified? Partial (knew there was a breach but didn't calculate precise amounts)
- Prevention created? No (manual investigation only)

**What the agent found (Phase 3):**
- Time taken: 26 seconds
- Root cause found? Yes
- SLA breach identified? Yes (QuickMart breached at ₹1,21,450, FuelPlus safe at ₹87,200)
- Prevention created? Yes (3 live alarms created on CloudWatch)

**What I missed that the agent caught:**
The exact correlation between Kinesis stream metrics and Snowflake row count divergence in real-time, along with the precise financial impact calculation across multiple merchant SLAs.

**Why the agent caught it:**
The agent is equipped with custom AWS and Snowflake tools that query metadata and logs in parallel, allowing it to perform sub-second mathematical comparisons and query databases with zero manual overhead.

---

## Judgment Questions

**Forensics Agent:**
*The agent found the root cause by correlating Lambda version history with Snowflake query history. What is the one CloudWatch alarm that would have caught this at 02:12 instead of 09:03? Write it as a metric alarm definition.*

Your answer:
A CloudWatch Metric Alarm based on a custom metric tracking the row count divergence or Snowflake zero load rate would have caught this. Here is the Metric Alarm Definition:
```json
{
  "AlarmName": "sigma-snowflake-zero-load",
  "AlarmDescription": "Triggered when Snowflake loads 0 rows over 2 consecutive ingestion windows, indicating a silent schema breakdown.",
  "MetricName": "RowsLoaded",
  "Namespace": "SigmaPipeline",
  "Statistic": "Sum",
  "Period": 300,
  "EvaluationPeriods": 2,
  "Threshold": 0.0,
  "ComparisonOperator": "LessThanOrEqualToThreshold",
  "TreatMissingData": "breaching",
  "AlarmActions": ["arn:aws:sns:us-east-1:526156223837:sigma-alerts"]
}
```

---

**Recovery Agent:**
*The recovery used transaction_id as the idempotency key. What happens if a legitimate duplicate transaction_id exists in the source data? How would you change the deduplication logic?*

Your answer:
If a legitimate duplicate `transaction_id` exists in the source stream (e.g. from rapid user retries or system re-submissions), the current idempotency filter would falsely identify it as a duplicate and discard it, resulting in legitimate transaction loss.
To fix this, we should change the deduplication key to be a compound hash of:
`MD5(transaction_id + customer_id + amount + transaction_date)`
Additionally, we can include the Kinesis shard partition key or record sequence number to ensure that identical values appearing at different locations/times are processed correctly.

---

**Hardening Agent:**
*The sigma-lambda-version-change alarm fires on any Lambda error spike after a version change. Your team deploys 20 Lambda functions per day in prod. Would you keep this alarm? If yes, how do you stop it from spamming? If no, what replaces it?*

Your answer:
No, keeping this alarm in its current format in a high-deployment CI/CD environment (20 deploys/day) would cause extreme alarm fatigue and spam.
Instead of keeping it globally active, we should replace it with:
1. **Targeted Deployment Windows:** Use anomaly detection bands (CloudWatch Anomaly Detection) that adjust metrics dynamically.
2. **Integration with Deployment Pipelines:** Hook the alarm directly to the AWS CodeDeploy lifecycle events. The alarm should only remain active for a 30-minute "baking period" after a deployment. If no error spikes are detected within the baking period, the alarm automatically deactivates.
3. **Log Metric Filters:** Replace standard error counts with structured error pattern matchers (e.g., `JSONValidationError`), which specifically point to code regressions rather than transient network drops.

---

## Your Honest Reflection

**Which part of the manual investigation took longest and why:**
Extracting the sample S3 record and parsing the raw nested JSON block manually to identify that `merchant_name` was changed to `merchant_nm`. Without formatted visualization, scanning raw attributes and comparing them column-by-column against the Snowflake table catalog took the most time.

**What would have happened if this hit prod at 2 AM with no agents:**
It would have gone completely unnoticed until business hours when merchants started complaining about missing payouts and dashboard discrepancies. By that time (over 7 hours later), millions of transactions would have accumulated in the S3 bronze buffer. Attempting manual reprocessing, deduplication, and reconciliation across hundreds of active merchants under severe business pressure would be a chaotic, high-risk operation prone to further data corruption.

**One thing you would add to this platform that none of the 6 agents currently do:**
An **Automated Schema Evolution Agent** that dynamically detects slight schema mutations (like `merchant_name` -> `merchant_nm`) and, instead of failing the pipeline, temporarily routes the malformed data to a Schema Buffer, auto-generates a migration script, and alerts the engineering team with a pre-configured pull request to update the Snowflake table layout.

---
