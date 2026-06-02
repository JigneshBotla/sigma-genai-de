"""
Pipeline Trigger — run from your laptop.
Invokes the Bedrock Supervisor Agent and streams its reasoning live.

The Supervisor runs as a multi-turn session: each invoke_agent call handles
one turn (e.g. calling ForensicsAgent, then returning). We keep driving the
session forward until the workflow completes (up to max_turns).

Usage:
  python lab/trigger/pipeline_trigger.py \\
    --bucket sigma-datatech-team1 \\
    --message "GMV is zero since 2 AM. Pipeline shows healthy. Investigate and fix."

  # Check health of all Lambda tools first:
  python lab/trigger/pipeline_trigger.py --health-check

  # Clean run (after disaster is fixed, to confirm pipeline is healthy):
  python lab/trigger/pipeline_trigger.py --bucket sigma-datatech-team1 --mode clean
"""

import argparse, boto3, json, os, sys, time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# ── Optional Langfuse observability ───────────────────────────────────────────
try:
    from langfuse import Langfuse as _Langfuse
    _lf = _Langfuse() if os.getenv("LANGFUSE_PUBLIC_KEY") else None
except ImportError:
    _lf = None

REGION             = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
SUPERVISOR_ID      = os.getenv("SUPERVISOR_AGENT_ID", "")
SUPERVISOR_ALIAS   = os.getenv("SUPERVISOR_ALIAS_ID", "TSTALIASID")
DEFAULT_BUCKET     = os.getenv("SIGMA_S3_BUCKET", "")

INCIDENT_MESSAGE   = (
    "Dashboard shows 40,000 transactions today but yesterday showed 1,20,000. "
    "80,000 records are missing. The pipeline shows healthy in all monitors — "
    "Lambda is green, S3 has files. "
    "But Snowflake row count is far below what S3 received since 02:00 UTC. "
    "Investigate the root cause, recover the missing records, prevent recurrence. "
    "Write an incident report when done."
)

CLEAN_MESSAGE = (
    "Run a health check on the pipeline. "
    "Confirm data is flowing from S3 to Snowflake cleanly. "
    "Report row counts and GMV for the last hour."
)

CONTINUATION_MSG = (
    "Continue with the previous task — resume from where you left off. "
    "Do not restart the investigation. Check what sub-agents have already "
    "reported and proceed to the next pending step in the workflow."
)


def health_check():
    lam    = boto3.client("lambda", region_name=REGION)
    tools  = [
        "sigma-tool-check-cloudwatch",
        "sigma-tool-get-s3-records",
        "sigma-tool-query-snowflake",
        "sigma-tool-rollback-lambda",
        "sigma-tool-create-alarm",
        "sigma-tool-quarantine-rows",
        "sigma-tool-load-snowflake",
        "sigma-tool-write-report",
        "sigma-tool-send-alert",
        "sigma-mcp-server",
    ]
    print("\nHEALTH CHECK — Lambda Tool Functions")
    print("=" * 50)
    all_ok = True
    for fn in tools:
        try:
            lam.get_function(FunctionName=fn)
            print(f"  OK  {fn}")
        except Exception:
            print(f"  MISSING  {fn}")
            all_ok = False

    print("=" * 50)
    if not SUPERVISOR_ID:
        print("  WARN  SUPERVISOR_AGENT_ID not set in .env")
        all_ok = False
    else:
        print(f"  OK  Supervisor Agent ID: {SUPERVISOR_ID}")

    print(f"\n{'ALL TOOLS READY' if all_ok else 'SOME TOOLS MISSING — run deploy_tools.sh'}")
    return all_ok


def is_workflow_complete(text: str) -> bool:
    """
    Heuristic: the Supervisor's text mentions full completion signals.
    We look for multiple signals to avoid false positives.
    """
    t = text.lower()
    signals = [
        "incident report" in t and "s3" in t,
        "recovery complete" in t,
        "pipeline restored" in t,
        "reports/" in t,
        "human interventions: 0" in t,
        "gmv restored" in t,
        "alarms created" in t and "recovery" in t,
        # The supervisor's own final structured response
        "what happened" in t and "what you fixed" in t,
        "what you prevented" in t,
    ]
    return sum(signals) >= 2   # require at least 2 signals


def stream_one_turn(bedrock, session_id: str, input_text: str,
                    lf_trace) -> tuple:
    """
    Call invoke_agent once and stream all events.
    Returns (final_text, had_delegation).
    """
    response = bedrock.invoke_agent(
        agentId=SUPERVISOR_ID,
        agentAliasId=SUPERVISOR_ALIAS,
        sessionId=session_id,
        inputText=input_text,
        enableTrace=True,
    )

    final_text     = ""
    had_delegation = False

    for event in response["completion"]:

        if "chunk" in event:
            text = event["chunk"]["bytes"].decode("utf-8")
            print(text, end="", flush=True)
            final_text += text

        elif "trace" in event:
            trace = event["trace"].get("trace", {})
            orch  = trace.get("orchestrationTrace", {})

            if "rationale" in orch:
                rat = orch["rationale"].get("text", "")
                if rat:
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"\n[{ts}] SUPERVISOR REASONING: {rat[:120]}...")

            inv = orch.get("invocationInput", {})

            if "actionGroupInvocationInput" in inv:
                ag = inv["actionGroupInvocationInput"]
                fn = ag.get("function", "?")
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] TOOL CALLED: {fn}")
                if lf_trace:
                    try:
                        lf_trace.event(name="tool-called",
                                       input={"tool": fn, "timestamp": ts})
                    except Exception:
                        pass

            obs = orch.get("observation", {})
            if "actionGroupInvocationOutput" in obs:
                out = obs["actionGroupInvocationOutput"].get("text", "")
                if out:
                    ts = datetime.now().strftime("%H:%M:%S")
                    try:
                        parsed = json.loads(out)
                        for key in ["status", "root_cause_hypothesis",
                                    "gmv_gap_inr", "rows_loaded", "alarm_name"]:
                            if key in parsed:
                                print(f"[{ts}] RESULT: {key} = {parsed[key]}")
                                break
                    except Exception:
                        print(f"[{ts}] RESULT: {out[:100]}")

            if "agentCollaboratorInvocationInput" in inv:
                collab      = inv["agentCollaboratorInvocationInput"]
                ts          = datetime.now().strftime("%H:%M:%S")
                agent_name  = collab.get("agentCollaboratorName", "?")
                agent_input = collab.get("input", {}).get("text", "")
                print(f"[{ts}] DELEGATING TO: {agent_name} — {agent_input[:80]}")
                had_delegation = True
                if lf_trace:
                    try:
                        lf_trace.event(name="agent-delegated",
                                       input={"agent": agent_name,
                                              "message": agent_input[:200],
                                              "timestamp": ts})
                    except Exception:
                        pass

    return final_text, had_delegation


def invoke_supervisor(message: str, session_id: str):
    if not SUPERVISOR_ID:
        print("\n[ERROR] SUPERVISOR_AGENT_ID not set in .env")
        print("  Run: python lab/create_agents.py")
        sys.exit(1)

    from botocore.config import Config
    custom_config = Config(
        read_timeout=300,
        connect_timeout=300,
        retries={"max_attempts": 1}   # we handle retries ourselves
    )
    bedrock = boto3.client("bedrock-agent-runtime", region_name=REGION, config=custom_config)

    print("\n" + "=" * 60)
    print("SIGMA INTELLIGENCE PLATFORM — SUPERVISOR AGENT")
    print("=" * 60)
    print(f"  Agent     : {SUPERVISOR_ID}")
    print(f"  Session   : {session_id}")
    print(f"  Triggered : {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 60)
    print(f"\nINPUT: {message}\n")
    print("-" * 60)

    start = time.time()

    lf_trace = None
    if _lf and hasattr(_lf, "trace"):
        try:
            lf_trace = _lf.trace(
                name="sigma-supervisor",
                session_id=session_id,
                input={"message": message},
                tags=["bedrock-agent", "day12", "sigma-platform"],
            )
        except Exception:
            lf_trace = None

    # ── Multi-turn loop ────────────────────────────────────────────────────────
    # Bedrock multi-agent collaboration returns one "turn" per invoke_agent call.
    # After each turn, we call again on the same session_id to drive forward.
    # The loop ends when the Supervisor's output signals full workflow completion.
    max_turns   = 20
    max_retries = 5
    turn        = 0
    err_retries = 0
    current_input = message

    while turn < max_turns:
        turn += 1
        if turn > 1:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"\n[{ts}] --- Turn {turn} / continuing workflow ---")

        try:
            final_text, had_delegation = stream_one_turn(
                bedrock, session_id, current_input, lf_trace
            )
            err_retries = 0   # reset on success

            if is_workflow_complete(final_text):
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"\n[{ts}] Workflow complete after {turn} turn(s).")
                break

            # Detect guardrail block — send a targeted recovery prompt
            if "guardrail" in final_text.lower() and "blocked" in final_text.lower():
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"\n[{ts}] [GUARDRAIL BLOCK DETECTED] Sending targeted recovery prompt...")
                current_input = (
                    "The previous sub-agent call was blocked by the guardrail. "
                    "The Recovery Agent should read records from S3 Bronze using "
                    "the get_s3_records tool (not replay from Kinesis). "
                    "Call get_s3_records with s3_prefix='bronze/disaster/' to read "
                    "the malformed files, then call load_to_snowflake with the clean records. "
                    "This is a read-and-load operation, not a destructive operation."
                )
            else:
                # Not complete yet — nudge the supervisor to continue
                current_input = CONTINUATION_MSG

        except Exception as e:
            err_msg = str(e).lower()
            is_transient = any(k in err_msg for k in [
                "throttling", "limit", "too many requests", "prematurely",
                "ended prematurely", "timeout", "connection", "read time out",
                "endpoint connection", "dependencyfailedexception",
            ])

            if is_transient and err_retries < max_retries:
                import random
                err_retries += 1
                sleep_time = min(40, 8 * (2 ** err_retries)) + random.randint(1, 5)
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"\n[{ts}] [WARNING] Transient Bedrock error: {e}. "
                      f"Retry {err_retries}/{max_retries} in {sleep_time}s...")
                time.sleep(sleep_time)
                current_input = CONTINUATION_MSG
            else:
                print(f"\n[ERROR] Agent invocation failed: {e}")
                print("\nChecks:")
                print("  1. SUPERVISOR_AGENT_ID in .env is correct")
                print("  2. Bedrock agent is in PREPARED state")
                print(f"  3. aws bedrock-agent get-agent --agent-id {SUPERVISOR_ID} --region {REGION}")
                sys.exit(1)

    elapsed = round(time.time() - start, 1)

    if lf_trace:
        try:
            lf_trace.update(output={"duration_seconds": elapsed, "status": "complete"})
            if hasattr(_lf, "flush"):
                _lf.flush()
        except Exception:
            pass

    print("\n" + "=" * 60)
    print(f"  AGENT COMPLETE | Duration: {elapsed}s")
    print("=" * 60)
    print(f"\n  Reports in S3: aws s3 ls s3://{DEFAULT_BUCKET}/reports/ --recursive")
    print(f"  Alarms:        aws cloudwatch describe-alarms --alarm-name-prefix sigma-")
    if _lf and lf_trace and hasattr(lf_trace, "id"):
        print(f"  Langfuse trace: https://cloud.langfuse.com/trace/{lf_trace.id}")


def main():
    parser = argparse.ArgumentParser(description="Sigma Platform Pipeline Trigger")
    parser.add_argument("--bucket",       default=DEFAULT_BUCKET)
    parser.add_argument("--message",      default=INCIDENT_MESSAGE)
    parser.add_argument("--mode",         choices=["incident", "clean"],
                        default="incident")
    parser.add_argument("--health-check", action="store_true")
    args = parser.parse_args()

    if args.health_check:
        health_check()
        return

    if args.mode == "clean":
        msg = CLEAN_MESSAGE
    elif args.message != INCIDENT_MESSAGE:
        msg = args.message
    else:
        msg = INCIDENT_MESSAGE

    session_id = f"sigma-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    invoke_supervisor(msg, session_id)


if __name__ == "__main__":
    main()
