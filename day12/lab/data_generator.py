"""
Sigma DataTech Data Generator
Writes transaction records to S3 Bronze and directly to Snowflake.
No Kinesis or Firehose required.

Modes:
  --mode clean           → valid, well-formed records
  --mode chaos           → inject specific pain points

Inject options (use with --mode chaos):
  --inject schema_drift  → renames merchant_name → merchant_nm
  --inject pii_leak      → adds cust_ph, acct_no in plain text
  --inject quality_rot   → null PKs, negative amounts, bad dates

Usage:
  python lab/data_generator.py --mode clean --records 100
  python lab/data_generator.py --mode chaos --inject schema_drift --records 100
"""

import argparse, boto3, json, random, time, sys, os
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

REGION  = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
BUCKET  = os.getenv("SIGMA_S3_BUCKET", "")

MERCHANTS   = ["QuickMart","FuelPlus","CafeBlend","TechZone","MediPharm",
               "GroceryHub","PetCorner","AutoFix","TravelEasy","ByteStore"]
CATEGORIES  = ["retail","fuel","food","electronics","pharmacy",
               "grocery","pet","automotive","travel","tech"]
CURRENCIES  = ["INR","INR","INR","INR","INR","INR","USD","EUR","INR","INR"]
STATUSES    = ["completed","completed","completed","pending","failed"]
CITIES      = ["Bengaluru","Mumbai","Chennai","Delhi","Hyderabad","Pune"]
PAYMENTS    = ["UPI","card","netbanking","wallet"]
PHONES      = [f"+91{random.randint(7000000000,9999999999)}" for _ in range(50)]
ACCT_NOS    = [f"{random.randint(100000000000,999999999999)}" for _ in range(50)]
PIN_CODES   = ["560001","400001","600001","110001","500001"]


def rand_date(days_back=7):
    d = datetime.now() - timedelta(days=random.randint(0, days_back))
    return d.strftime("%Y-%m-%d")


def make_clean_record(idx):
    m = random.randint(0, 9)
    return {
        "transaction_id":   f"TXN{100000 + idx}",
        "merchant_name":    MERCHANTS[m],
        "category":         CATEGORIES[m],
        "amount":           round(random.uniform(50, 25000), 2),
        "currency":         CURRENCIES[m],
        "transaction_date": rand_date(),
        "status":           random.choice(STATUSES),
        "customer_id":      f"C{random.randint(1000,1099)}",
        "payment_method":   random.choice(PAYMENTS),
        "merchant_city":    random.choice(CITIES),
    }


def inject_schema_drift(record):
    record["merchant_nm"] = record.pop("merchant_name")
    return record


def inject_pii_leak(record):
    record["cust_ph"] = random.choice(PHONES)
    record["acct_no"] = random.choice(ACCT_NOS)
    return record


def inject_quality_rot(record, idx, n_records):
    pct = idx / n_records
    if pct < 0.06:
        record["transaction_id"] = ""
    elif pct < 0.10:
        record["amount"] = -abs(record["amount"])
    elif pct < 0.125:
        record["transaction_date"] = "99-99-9999"
    return record


def write_to_s3(s3, records, mode):
    if not BUCKET:
        print("  [WARN] SIGMA_S3_BUCKET not set — skipping S3 write")
        return None
    prefix = f"bronze/{mode}/{datetime.utcnow().strftime('%Y/%m/%d/%H')}/"
    key    = f"{prefix}batch_{int(time.time())}.json"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(records).encode(),
        ContentType="application/json",
    )
    return f"s3://{BUCKET}/{key}"


def write_to_snowflake(records):
    try:
        import snowflake.connector
    except ImportError:
        print("  [WARN] snowflake-connector-python not installed — skipping Snowflake write")
        return 0

    account   = os.getenv("SNOWFLAKE_ACCOUNT", "")
    user      = os.getenv("SNOWFLAKE_USER", "")
    password  = os.getenv("SNOWFLAKE_PASSWORD", "")
    database  = os.getenv("SNOWFLAKE_DATABASE", "SIGMA")
    schema    = os.getenv("SNOWFLAKE_SCHEMA", "SILVER")
    warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "SIGMA_WH")

    if not all([account, user, password]):
        print("  [WARN] Snowflake credentials not set — skipping Snowflake write")
        return 0

    try:
        conn = snowflake.connector.connect(
            account=account, user=user, password=password,
            database=database, schema=schema, warehouse=warehouse,
        )
        cur = conn.cursor()
        ts  = datetime.utcnow().isoformat()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS TRANSACTIONS (
                transaction_id   VARCHAR,
                merchant_name    VARCHAR,
                category         VARCHAR,
                amount           FLOAT,
                currency         VARCHAR,
                transaction_date DATE,
                status           VARCHAR,
                customer_id      VARCHAR,
                payment_method   VARCHAR,
                merchant_city    VARCHAR,
                _loaded_at       TIMESTAMP_TZ
            )
        """)

        cur.execute("""
            CREATE TEMPORARY TABLE IF NOT EXISTS temp_gen (
                transaction_id VARCHAR, merchant_name VARCHAR, category VARCHAR,
                amount FLOAT, currency VARCHAR, transaction_date DATE,
                status VARCHAR, customer_id VARCHAR, payment_method VARCHAR,
                merchant_city VARCHAR, _loaded_at TIMESTAMP_TZ
            )
        """)

        batch = [
            (r.get("transaction_id",""), r.get("merchant_name",""),
             r.get("category",""), float(r.get("amount",0) or 0),
             r.get("currency","INR"), r.get("transaction_date",""),
             r.get("status",""), r.get("customer_id",""),
             r.get("payment_method",""), r.get("merchant_city",""), ts)
            for r in records if r.get("transaction_id")
        ]

        cur.executemany(
            "INSERT INTO temp_gen VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            batch,
        )

        cur.execute(f"""
            MERGE INTO {database}.{schema}.TRANSACTIONS AS t
            USING temp_gen AS s ON t.transaction_id = s.transaction_id
            WHEN NOT MATCHED THEN INSERT (
                transaction_id, merchant_name, category, amount, currency,
                transaction_date, status, customer_id, payment_method,
                merchant_city, _loaded_at
            ) VALUES (
                s.transaction_id, s.merchant_name, s.category, s.amount,
                s.currency, s.transaction_date, s.status, s.customer_id,
                s.payment_method, s.merchant_city, s._loaded_at
            )
        """)

        cur.execute("SELECT COUNT(*) FROM temp_gen")
        loaded = cur.fetchone()[0]
        conn.commit()
        conn.close()
        return loaded

    except Exception as e:
        print(f"  [WARN] Snowflake write failed: {e}")
        return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode",    choices=["clean","chaos"], default="clean")
    parser.add_argument("--inject",  choices=["schema_drift","pii_leak","quality_rot","all"], default=None)
    parser.add_argument("--records", type=int, default=100)
    parser.add_argument("--stream",  default=None, help="ignored — kept for compatibility")
    parser.add_argument("--region",  default=REGION)
    args = parser.parse_args()

    if args.mode == "chaos" and args.inject is None:
        print("[ERROR] --mode chaos requires --inject flag")
        sys.exit(1)

    print("=" * 60)
    print("SIGMA DATATECH — DATA GENERATOR")
    print("=" * 60)
    print(f"  Mode   : {args.mode.upper()}")
    if args.inject:
        print(f"  Inject : {args.inject.upper()}")
    print(f"  Records: {args.records}")
    print(f"  Bucket : {BUCKET or '(not set)'}")
    print("=" * 60)

    s3_direct_mode = False
    s3_client = None
    bucket_name = os.getenv("SIGMA_S3_BUCKET", "sigma-datatech-nexusteam")

    try:
        client = boto3.client("kinesis", region_name=args.region)
        # Quick check — will raise if credentials or stream don't exist
        client.describe_stream_summary(StreamName=args.stream)
    except Exception as e:
        print(f"[WARNING] Kinesis stream '{args.stream}' is unavailable/not subscribed: {e}")
        print("          Switching to Direct S3 Ingestion Mode (No-Kinesis Fallback)!")
        s3_direct_mode = True
        s3_client = boto3.client("s3", region_name=args.region)

    sent = 0
    errors = 0
    start = time.time()
    records_list = []

    for i in range(args.records):
        rec = make_clean_record(i)
        if args.mode == "chaos":
            if args.inject in ("schema_drift", "all"):
                rec = inject_schema_drift(rec)
            if args.inject in ("pii_leak", "all"):
                rec = inject_pii_leak(rec)
            if args.inject in ("quality_rot", "all"):
                rec = inject_quality_rot(rec, i, args.records)
        records.append(rec)

        # Only print every 10th record to keep output readable
        verbose = (i % 10 == 0)
        
        if s3_direct_mode:
            records_list.append(record)
            if verbose:
                tid  = record.get("transaction_id") or record.get("transaction_id", "NULL")
                name = record.get("merchant_name") or record.get("merchant_nm", "?")
                amt  = record.get("amount", 0)
                curr = record.get("currency", "?")
                print(f"  [S3-DIR] {str(tid):12} | {name:12} | {curr} {float(amt):>10,.2f}")
            sent += 1
        else:
            ok = send_to_kinesis(client, args.stream, record, verbose=verbose)
            if ok:
                sent += 1
            else:
                errors += 1

    print("=" * 60)

    # Write to S3
    s3_path = write_to_s3(s3, records, args.mode)
    if s3_path:
        print(f"  S3   : {s3_path}")

    # Load to Snowflake (clean mode only — chaos is for investigation scenarios)
    if args.mode == "clean":
        loaded = write_to_snowflake(records)
        print(f"  Snowflake: {loaded} rows loaded (MERGE INTO)")

    if s3_direct_mode and records_list:
        # Write records to S3 as standard JSON arrays in batches of 50
        batch_size = 50
        files_written = 0
        from datetime import datetime
        # Use fixed 02 hour path for chaos mode to match disaster scenario, or dynamic path for clean mode
        if args.mode == "chaos":
            prefix = "bronze/disaster/2026/06/04/02/"
        else:
            prefix = f"bronze/clean/{datetime.utcnow().strftime('%Y/%m/%d/%H')}/"
            
        print(f"\n  [S3-DIR] Writing records to S3 bucket '{bucket_name}' under prefix '{prefix}'...")
        for j in range(0, len(records_list), batch_size):
            batch = records_list[j:j + batch_size]
            key = f"{prefix}batch_direct_{int(time.time())}_{j//batch_size:03d}.json"
            try:
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=key,
                    Body=json.dumps(batch).encode("utf-8"),
                    ContentType="application/json"
                )
                files_written += 1
            except Exception as s3_err:
                print(f"  [ERROR] S3 write failed: {s3_err}")
                errors += len(batch)
                sent -= len(batch)
        print(f"  [S3-DIR] Successfully uploaded {sent} records to {files_written} files in S3.")

        # If clean mode, also load records directly into Snowflake for immediate verification
        if args.mode == "clean":
            print(f"\n  [S3-DIR] Ingesting {len(records_list)} clean records into Snowflake database...")
            try:
                import snowflake.connector
                from dotenv import load_dotenv
                load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
                
                conn = snowflake.connector.connect(
                    account=os.getenv("SNOWFLAKE_ACCOUNT"),
                    user=os.getenv("SNOWFLAKE_USER"),
                    password=os.getenv("SNOWFLAKE_PASSWORD"),
                    database=os.getenv("SNOWFLAKE_DATABASE", "SIGMA"),
                    schema=os.getenv("SNOWFLAKE_SCHEMA", "SILVER"),
                    warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "SIGMA_WH"),
                )
                cur = conn.cursor()
                
                # Ensure target table exists or is ready, then load
                ts = datetime.utcnow().isoformat()
                cur.execute("""
                    CREATE TEMPORARY TABLE IF NOT EXISTS temp_transactions (
                        transaction_id   VARCHAR,
                        merchant_name    VARCHAR,
                        category         VARCHAR,
                        amount           FLOAT,
                        currency         VARCHAR,
                        transaction_date DATE,
                        status           VARCHAR,
                        customer_id      VARCHAR,
                        payment_method   VARCHAR,
                        merchant_city    VARCHAR,
                        _loaded_at       TIMESTAMP_TZ
                    )
                """)
                
                batch_values = []
                for rec in records_list:
                    batch_values.append((
                        rec.get("transaction_id", ""),
                        rec.get("merchant_name", rec.get("merchant_nm", "")),
                        rec.get("category", ""),
                        float(rec.get("amount", 0) or 0),
                        rec.get("currency", "INR"),
                        rec.get("transaction_date", ""),
                        rec.get("status", ""),
                        rec.get("customer_id", ""),
                        rec.get("payment_method", ""),
                        rec.get("merchant_city", ""),
                        ts,
                    ))
                
                cur.executemany(
                    """INSERT INTO temp_transactions VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    batch_values,
                )
                
                table_name = f"{os.getenv('SNOWFLAKE_DATABASE','SIGMA')}.{os.getenv('SNOWFLAKE_SCHEMA','SILVER')}.TRANSACTIONS"
                cur.execute(f"""
                    MERGE INTO {table_name} AS target
                    USING temp_transactions AS src
                    ON target.transaction_id = src.transaction_id
                    WHEN NOT MATCHED THEN INSERT (
                        transaction_id, merchant_name, category, amount, currency,
                        transaction_date, status, customer_id, payment_method,
                        merchant_city, _loaded_at
                    ) VALUES (
                        src.transaction_id, src.merchant_name, src.category, src.amount,
                        src.currency, src.transaction_date, src.status, src.customer_id,
                        src.payment_method, src.merchant_city, src._loaded_at
                    )
                """)
                
                cur.execute("SELECT COUNT(*) FROM temp_transactions")
                total = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM {table_name} WHERE _loaded_at = '{ts}'")
                rows_loaded = cur.fetchone()[0]
                print(f"  [S3-DIR] Snowflake load successful! Attempted: {total}, Loaded: {rows_loaded}")
                conn.commit()
                conn.close()
            except Exception as se:
                print(f"  [WARNING] Snowflake load failed: {se}")

    elapsed = round(time.time() - start, 1)
    print("=" * 60)
    print(f"  Done. {len(records)} records processed.")
    if args.mode == "clean":
        print(f"  Run: python lab/investigate/check_snowflake.py to verify.")
    print("=" * 60)


if __name__ == "__main__":
    main()
