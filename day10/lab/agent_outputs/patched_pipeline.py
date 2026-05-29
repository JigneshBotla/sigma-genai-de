# Patched by Self-Healing Agent — 2026-05-29T17:46:49.978643
# Attempts needed: 5

import duckdb
import pandas as pd

DB_PATH = r"/Users/as-mac-1184/Desktop/GenAI_Training/sigma-genai-de/day10/lab/sigma_platform.duckdb"

def run_merchant_report():
    conn = duckdb.connect(DB_PATH, read_only=False)
    df = conn.execute("SELECT * FROM silver_transactions WHERE amount > 0").fetchdf()

    total = df["amount"].sum()

    df2 = df.groupby("merchant_id").agg({"amount": "mean"}).reset_index()
    df2.columns = ["merchant_id", "avg_amount"]

    conn.execute("CREATE TABLE IF NOT EXISTS report (merchant_id TEXT, avg_amount DOUBLE)")
    conn.executemany("INSERT INTO report VALUES (?,?)", df2.values.tolist())

    conn.close()
    print(f"Done. Total: {total:.2f}, Merchants: {len(df2)}")

    top = df2.iloc[0]["merchant_id"]
    print(f"Top merchant by avg amount: {top}")

if __name__ == "__main__":
    run_merchant_report()