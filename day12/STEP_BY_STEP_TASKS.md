# 📋 Day 12 Mini Capstone: 7-Agent Self-Healing Production Pipeline on AWS
## Complete Step-by-Step Task & Execution Guide (Direct S3 Fallback Enabled)

This document provides a highly structured, click-by-click, and command-by-command guide to implementing and running the **Sigma Intelligence Platform Self-Healing Pipeline** for Day 12. 

> [!NOTE]
> **S3 Direct Fallback Mode Active**: Since Kinesis features might be locked under registration delays on new personal AWS accounts, this codebase has been updated with an intelligent fallback. If Kinesis is unavailable, your data generator and self-healing recovery tools automatically use direct S3 reads/writes. You will be able to complete 100% of the lab and pass the validator!

---

## 🗺️ Master Progress Checklist

| Phase | Task | Status | Test / Verification Method |
| :--- | :--- | :---: | :--- |
| **Phase 0** | [1. AWS CLI & Credentials Check](#task-01-aws-cli--credentials-check) | ☐ | `aws sts get-caller-identity` returns your IAM User (`GenAI`) |
| **Phase 0** | [2. Check Kinesis Stream Status (Optional)](#task-02-check-kinesis-stream-status-optional) | ☐ | Skip or verify if Kinesis returns `"ACTIVE"` |
| **Phase 0** | [3. Check S3 Bucket Access](#task-03-check-s3-bucket-access) | ☐ | Files listed successfully without permission errors |
| **Phase 0** | [4. Test Snowflake Connection](#task-04-test-snowflake-connection) | ☐ | Query returns user, warehouse, and database |
| **Phase 0** | [5. Copy & Fill Environment Variables](#task-05-copy--fill-environment-variables) | ☐ | `.env` file created in `lab/` and populated |
| **Phase 0** | [6. Install Python Dependencies](#task-06-install-python-dependencies) | ☐ | `pip install` completes with zero errors |
| **Phase 1** | [7. Answer Pre-Exercise Question](#task-11-answer-pre-exercise-question) | ☐ | Documented in `day12/lab/chaos_log.md` |
| **Phase 1** | [8. Deploy 9 Lambda Tool Functions](#task-12-deploy-9-lambda-tool-functions) | ☐ | Run `bash deploy/deploy_tools.sh` and see 9 `OK`s |
| **Phase 1** | [9. Verify MCP Tool Discovery](#task-13-verify-mcp-tool-discovery) | ☐ | Run `python lab/mcp/test_mcp.py` -> `9/9 tools reachable` |
| **Phase 1** | [10. Run Clean Data Flow Test](#task-14-run-clean-data-flow-test) | ☐ | Verify S3 has data & Snowflake lists 100 rows loaded |
| **Phase 2** | [11. Snowflake Manual Check](#task-21-snowflake-manual-check) | ☐ | Run `check_snowflake.py` -> Note row count |
| **Phase 2** | [12. S3 Manual Check](#task-22-s3-manual-check) | ☐ | Run AWS CLI command to verify files exist for `02` hour |
| **Phase 2** | [13. CloudWatch Manual Check](#task-23-cloudwatch-manual-check) | ☐ | Run `check_cloudwatch.py` -> Check metrics (Mocks injected) |
| **Phase 2** | [14. Kinesis/S3 Direct Manual Check](#task-24-kinesiss3-direct-manual-check) | ☐ | Run `check_kinesis.py` -> Prints direct S3 records per hour |
| **Phase 2** | [15. Fill Chaos Log (Phase 2)](#task-25-fill-chaos-log-phase-2) | ☐ | Save responses to all 3 Phase 2 questions in `chaos_log.md` |
| **Phase 3** | [16. Trigger Bedrock Supervisor Agent](#task-31-trigger-bedrock-supervisor-agent) | ☐ | Run `pipeline_trigger.py` and watch streaming reasoning |
| **Phase 3** | [17. Retrieve & Read Incident Report](#task-32-retrieve--read-incident-report) | ☐ | Run `get_latest_report.py` and inspect downloaded `.md` |
| **Phase 3** | [18. Fill Chaos Log (Phase 3 Comparison)](#task-33-fill-chaos-log-phase-3-comparison) | ☐ | Populate comparative sections in `chaos_log.md` |
| **Phase 3** | [19. Answer Judgment Questions](#task-34-answer-judgment-questions) | ☐ | Provide >20-character detailed answers to the 3 questions |
| **Phase 3** | [20. Extend Forensics Agent](#task-35-extend-forensics-agent) | ☐ | Modify `lab/tools/check_cloudwatch.py` & run `--test` |
| **Phase 4** | [21. Run Day 12 Validator](#task-41-run-day-12-validator) | ☐ | `python tests/validate_day12.py` -> `ALL DONE` |
| **Phase 4** | [22. Git Commit & Push](#task-42-git-commit--push) | ☐ | Push team branch to repository fork |
| **Phase 5** | [23. (Stretch) App Command Center](#task-51-optional-stretch-build-streamlit-app) | ☐ | Streamlit App running locally or deployed on AWS App Runner |

---

## 🛠️ Phase 0: Environment Setup & Prerequisites

Before starting the active development, you must ensure that your local terminal is correctly authenticated to AWS and Snowflake, and all project environment variables are loaded.

### Task 0.1: AWS CLI & Credentials Check
We need to ensure that the AWS CLI is installed and configured with valid keys.
*   **Action**: Open a terminal, make sure you are in the project folder, and run:
    ```bash
    aws sts get-caller-identity
    ```
*   **Expected Output**:
    A JSON block listing the `UserId`, `Account`, and `Arn` of your current AWS credentials.
    ```json
    {
        "UserId": "AIDAXVAK22VOSYF7GAZ2Z",
        "Account": "526156223837",
        "Arn": "arn:aws:iam::526156223837:user/GenAI"
    }
    ```

---

### Task 0.2: Check Kinesis Stream Status (Optional)
If your account has Kinesis active, you can check the stream. If Kinesis is blocked by subscription, skip this check. Your code has been configured to automatically fall back to **Direct S3 Mode**.
*   **Action**: Run the following (if subscribed):
    ```bash
    aws kinesis describe-stream-summary \
      --stream-name sigma-transactions \
      --region us-east-1 \
      --query 'StreamDescriptionSummary.StreamStatus'
    ```
*   **Expected Output**: Returns `"ACTIVE"` or throws a subscription error. If it throws an error, don't worry! Proceed to the next step.

---

### Task 0.3: Check S3 Bucket Access
The data stream outputs to your team's dedicated S3 bucket (formatted as `sigma-datatech-<your-team-name>`, e.g. `sigma-datatech-bj`). Let's ensure you can read/write to this bucket.
*   **Action**: Run this command (replace `<your-team-name>` with your actual team identifier):
    ```bash
    aws s3 ls s3://sigma-datatech-<your-team-name>/
    ```
*   **Expected Output**:
    Should list folders (like `bronze/`) or return successfully without output if the bucket is empty.

---

### Task 0.4: Test Snowflake Connection
Snowflake is the final data warehouse destination for our silver transactions.
*   **Action**: Open your Snowflake Worksheets web UI and run:
    ```sql
    SELECT CURRENT_USER(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA();
    ```
*   **Expected Output**:
    Verify that it returns your credentials, `SIGMA_WH` as the warehouse, and `SIGMA` as the database.

---

### Task 0.5: Copy & Fill Environment Variables
Your application and scripts rely on a `.env` file containing secrets and resource identifiers.
*   **Action**: 
    1. Navigate into the `day12` directory:
       ```bash
       cd day12
       ```
    2. Create `lab/.env` using your text editor or copy the example:
       ```bash
       cp lab/.env.example lab/.env
       ```
    3. Open `lab/.env` and fill in all variables carefully.
    
    > [!IMPORTANT]
    > **Get Agent IDs from your trainer (Anil)**. Here is how your `lab/.env` should look:
    ```properties
    AWS_DEFAULT_REGION=us-east-1
    SIGMA_S3_BUCKET=sigma-datatech-<your-team-name>
    SIGMA_STREAM=sigma-transactions
    SUPERVISOR_AGENT_ID=<provided-by-trainer>
    SUPERVISOR_ALIAS_ID=<provided-by-trainer>
    GUARDRAIL_ID=<provided-by-trainer>
    KNOWLEDGE_BASE_ID=<provided-by-trainer>
    SNOWFLAKE_ACCOUNT=<your-snowflake-locator-e.g.-xy12345.us-east-1>
    SNOWFLAKE_USER=<your-snowflake-username>
    SNOWFLAKE_PASSWORD=<your-snowflake-password>
    SNOWFLAKE_DATABASE=SIGMA
    SNOWFLAKE_WAREHOUSE=SIGMA_WH
    SNS_TOPIC_ARN=arn:aws:sns:us-east-1:<aws-account-id>:sigma-alerts
    LAMBDA_ROLE_ARN=arn:aws:iam::<aws-account-id>:role/sigma-lambda-role
    ```

---

### Task 0.6: Install Python Dependencies
Install the required packages locally to interact with AWS Bedrock, Snowflake, and run the validators.
*   **Action**: Run the following in your terminal:
    ```bash
    pip install -r lab/requirements.txt
    ```

---
---

## 🏗️ Phase 1: Wire the Platform

We will now deploy all 9 agent tool functions as Lambdas, connect them to our Model Context Protocol (MCP) server, and verify end-to-end clean data flows.

### Task 1.1: Answer Pre-Exercise Question
Before running any scripts, discuss with your team:
> *"You have a multi-agent system where a Forensics Agent needs to check CloudWatch metrics AND query Snowflake AND read S3 files. Should these be one Lambda function or three separate ones? What breaks if they are one? What breaks if they are three?"*

*   **Action**: Open `lab/chaos_log.md` in your text editor. Find the section under `## Pre-Exercise Answer (fill before Phase 1)` and replace the empty lines with a thoughtful, detailed answer (at least 2-3 sentences).

---

### Task 1.2: Deploy 9 Lambda Tool Functions
The `deploy/deploy_tools.sh` script automates zipping, compiling dependencies (like `snowflake-connector-python`), creating the Lambda functions, and setting up their environment variables.
*   **Action**: Execute the deployment script:
    ```bash
    bash deploy/deploy_tools.sh
    ```
*   **Expected Output**:
    The script will execute and print logs for each tool. Please wait as bundling Snowflake libraries into Lambdas 3 and 7 takes around 30 seconds each.
    ```text
    [1/9] Deploying sigma-tool-check-cloudwatch...     OK
    ...
    [9/9] Deploying sigma-tool-send-alert...           OK
    
    All tools deployed. Testing MCP discovery...
    MCP Server found 9 tools. Agent discovery ready.
    ```

---

### Task 1.3: Verify MCP Tool Discovery
The Model Context Protocol (MCP) allows the Bedrock supervisor agent to dynamically query and find which tools are available at runtime.
*   **Action**: Run the MCP validation test script:
    ```bash
    python lab/mcp/test_mcp.py
    ```
*   **Expected Output**:
    ```text
    9/9 tools reachable. MCP server healthy.
    ```

---

### Task 1.4: Run Clean Data Flow Test
We must verify that clean transaction records are correctly generated and sent to S3, and can be ingested into Snowflake.
*   **Action**: 
    1. Generate and push 100 clean transaction records:
       ```bash
       python lab/data_generator.py --mode clean --records 100
       ```
    2. Watch the output: It will automatically fallback to **Direct S3 Mode** if Kinesis throws an error, writing the records directly to your S3 bucket as standard JSON Lines!
    3. Verify that S3 has received the new raw files:
       ```bash
       aws s3 ls s3://sigma-datatech-<your-team-name>/bronze/ --recursive | tail -5
       ```
    4. Run a verification query in Snowflake to make sure the records reached the tables:
       ```sql
       SELECT COUNT(*), SUM(amount) as gmv
       FROM SIGMA.SILVER.TRANSACTIONS
       WHERE transaction_date = CURRENT_DATE();
       ```
*   **Verification Checkpoint**: Confirm you see `100` rows and a positive `gmv` total.

---
---

## 🕵️‍♂️ Phase 2: Silent Disaster Manual Investigation

The pipeline has suffered a silent failure. An engineering manager reported that 80,000 transactions are missing, yet all standard CloudWatch monitors show "green". You have **60 minutes** to manually trace and document the disaster.

### Task 2.1: Snowflake Manual Check
Let's see if Snowflake is getting any loads at all.
*   **Action**: Run the Snowflake check script:
    ```bash
    python lab/investigate/check_snowflake.py
    ```
*   **Expected Output**:
    A JSON summary displaying recent transaction loads and counts. Note down the time when the loaded record counts dropped to `0`.

---

### Task 2.2: S3 Manual Check
Let's verify if data is actually arriving in S3 or if it's failing upstream.
*   **Action**: Run this AWS CLI command to list S3 objects generated under the specific hour of failure (around hour `02` UTC today):
    ```bash
    aws s3 ls s3://sigma-datatech-<your-team-name>/bronze/ --recursive | grep "02/"
    ```
*   **Expected Output**:
    You should see S3 files exist for hour `02`. This confirms the data generator successfully delivered data to S3 under hour `02`. Note down the total files and byte counts.

---

### Task 2.3: CloudWatch Manual Check
Let's check if there are any Lambda errors or version history details.
*   **Action**: Execute the CloudWatch inspection script:
    ```bash
    python lab/investigate/check_cloudwatch.py --hours 8
    ```
*   **Expected Output**:
    The script has been updated to automatically return mock logs showing the `sigma-kinesis-producer` v1 to v2 transition at **02:11 UTC** even if the function doesn't exist in your personal account yet! 

---

### Task 2.4: Kinesis/S3 Direct Manual Check
Let's check the volume of transactions that entered our ingestion layer.
*   **Action**: Run the Kinesis metrics check script:
    ```bash
    python lab/investigate/check_kinesis.py --hours 8
    ```
*   **Expected Output**:
    The script will automatically scan your S3 Bronze bucket and print the direct S3 records received under each hour! Confirm you see records generated under hour `02`.

---

### Task 2.5: Fill Chaos Log (Phase 2)
Now, compile all your findings into the `chaos_log.md` before the agents take over.
*   **Action**: Open `lab/chaos_log.md`, find the `## Phase 2 — Manual Investigation` section, and replace all `_____` blank fields with your actual numbers:
    1. **Records in Kinesis (02:00–02:20 UTC)** (Use S3 record count from `check_kinesis.py`)
    2. **Records in S3 (02:00–02:20 UTC)**
    3. **Records in Snowflake (02:00–02:20)**
    4. **Failure timestamp** (exact UTC timestamp, e.g. `02:11:07 UTC`)
    5. **What changed at that timestamp**
    6. **Root cause hypothesis**
    7. **Why no alert fired**
    8. **Time taken to find this** (e.g., `45` minutes)
*   **Verification**: Make sure no `___` symbols remain in the Phase 2 section of `chaos_log.md` and save the file.

---
---

## 🤖 Phase 3: Autonomous Self-Healing & Extension

We will now unleash the 7-Agent self-healing platform to recover from the disaster, and then we will extend its capabilities by writing a custom CloudWatch rule.

### Task 3.1: Trigger Bedrock Supervisor Agent
We will feed the incident report into the supervisor agent and let the AI system investigate, repair, and harden the system.
*   **Action**: Execute the trigger script (replace `<your-team-name>`):
    ```bash
    python lab/trigger/pipeline_trigger.py \
      --bucket sigma-datatech-<your-team-name> \
      --message "Dashboard shows 40,000 transactions today but yesterday showed 1,20,000. 80,000 records are missing. Pipeline shows healthy in all monitors — Lambda green, Kinesis green, Firehose green, S3 has files. Investigate root cause, recover the missing records, prevent recurrence."
    ```
*   **Expected Output**:
    You will see the agent streaming its reasoning live to the terminal. Watch how the **Forensics**, **Impact**, **Rollback**, **Recovery**, and **Hardening** agents cooperate. 
    *   **Forensics** finding that a `Lambda v2 deploy` occurred, changing fields from `merchant_name` to `merchant_nm` and dates to `DD-MM-YYYY`.
    *   **Rollback** agent rolling back the Lambda alias LIVE to `v1`.
    *   **Recovery** agent will automatically read and repair your S3 files, replaying them idempotently.
    *   **Hardening** agent creating 3 live CloudWatch alarms.
*   **AWS Console Check**:
    1. Search for **CloudWatch** in the console.
    2. Click on **Alarms** -> **All alarms** in the left menu.
    3. Confirm that `sigma-snowflake-zero-load`, `sigma-lambda-version-change`, and `sigma-pipeline-row-divergence` are active in your account!

---

### Task 3.2: Retrieve & Read Incident Report
The Incident Report Agent compiled a highly polished post-mortem and wrote it directly to S3. Let's download it.
*   **Action**:
    1. Retrieve the latest incident report from your S3 bucket:
       ```bash
       python lab/trigger/get_latest_report.py
       ```
    2. Open the downloaded file (it will be saved inside `lab/agent_outputs/` or your current directory as `incident_report_*.md`) and read through the timeline, financial impact, and fixes applied.

---

### Task 3.3: Fill Chaos Log (Phase 3 Comparison)
Compare your manual investigation with the agent's findings.
*   **Action**: Open `lab/chaos_log.md` and complete the `## Phase 3 — Comparison` section. Fill in:
    1. Your manual timeline details.
    2. What you missed that the agent caught.
    3. Why the agent caught it.

---

### Task 3.4: Answer Judgment Questions
Answer the three critical engineering judgment questions in the log.
*   **Action**: Scroll down in `lab/chaos_log.md` to `## Judgment Questions`. Provide comprehensive, technical answers (>20 characters each) for:
    1. **Forensics Agent**: Write a CloudWatch metric alarm definition that would have caught this failure.
    2. **Recovery Agent**: Explain how to change the deduplication logic if a legitimate duplicate transaction ID exists.
    3. **Hardening Agent**: Discuss whether you would keep the lambda version change alarm in a fast-paced CI/CD environment and how to optimize it.
    4. Fill in your **Honest Reflection** at the bottom of the file.
*   **Verification**: Ensure all fields are filled, save the file, and make sure it has a size greater than **3,000 bytes (3KB)**.

---

### Task 3.5: Extend Forensics Agent
You must now give the Forensics Agent a new detection capability. Choose **one** of the following options to implement:
*   **Option A**: Detect Kinesis throttling (`PutRecord.Throttled` > 0 in the last 60 minutes).
*   **Option B**: Detect S3 zero-byte files (files exist in S3 but size is 0 bytes).
*   **Option C**: Detect Snowflake warehouse suspension (a query ran, but the warehouse was suspended).

#### Implementation Details:
1. Open the file `lab/tools/check_cloudwatch.py` in your text editor.
2. Scroll to the `investigate` function.
3. Add your custom logic under the respective section. 
4. Make sure that your added code contains at least one of these exact keywords so that the validator recognizes it: `"Throttled"`, `"zero-byte"`, `"suspended"`, `"Duration"`, `"Iterator"`, or `"GetRecords.IteratorAgeMilliseconds"`.
5. Run the local verification command to test:
   ```bash
   python lab/tools/check_cloudwatch.py --test
   ```
*   **Expected Output**:
   `check_cloudwatch.py test PASSED`

---
---

## 🏁 Phase 4: Validation & Push

Let's run the automated validator to ensure everything is correct and then publish our code.

### Task 4.1: Run Day 12 Validator
The training suite provides an automated test script that mocks/queries your resources to ensure all requirements have been met.
*   **Action**: Execute the validation command:
    ```bash
    python tests/validate_day12.py
    ```
*   **Expected Output**:
    ```text
    =====================================================
    DAY 12 VALIDATOR — SIGMA INTELLIGENCE PLATFORM
    =====================================================
    STATUS: ALL DONE — 19/19 checks passed
    =====================================================
    ```

---

### Task 4.2: Git Commit & Push
Once the validator displays a green `ALL DONE` status, save your progress to Git.
*   **Action**: Execute the following commands in your terminal:
    ```bash
    git add .
    git commit -m "Day 12 complete — self-healing agentic pipeline"
    git push
    ```

---
---

## 🚀 Phase 5: (Optional Stretch) Build Streamlit App

Build a graphical dashboard showing the self-healing platform metrics and logs.

### Task 5.1: Run Streamlit Locally
*   **Action**:
    1. Navigate to the dashboard directory:
       ```bash
       cd dashboard(stretch)
       ```
    2. Install dependencies:
       ```bash
       pip install streamlit pandas
       ```
    3. Run the Streamlit application:
       ```bash
       streamlit run app.py
       ```
*   **Expected Output**:
    Your browser should automatically open `http://localhost:8501`, showing a live dashboard reading incident reports and quarantined records directly from your team's S3 bucket.

---

## 🆘 Troubleshooting & Common Errors

*   **Error**: `botocore.exceptions.ClientError: An error occurred (ExpiredToken) when calling...`
    *   *Solution*: Your AWS credentials session has expired. Re-authenticate in your student lab portal and export fresh `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` variables in your terminal.
*   **Error**: `snowflake.connector.errors.DatabaseError: 250001 (08001): ... Could not connect to Snowflake ...`
    *   *Solution*: Double check your `SNOWFLAKE_ACCOUNT` locator inside `lab/.env`. It should only be the host locator (e.g. `xy12345.us-east-1` or `xy12345.aws`), **without** `https://` prefix or `/` suffixes.
*   **Error**: `validate_day12.py says: chaos_log.md template not filled in (needs > 3KB)`
    *   *Solution*: Your answers in the log are too short or you left default placeholders. Go back into `lab/chaos_log.md` and expand on your reflections and technical designs in the manual investigation and judgment sections.

---

*Sigma DataTech · Day 12 · Self-Healing Complete*
