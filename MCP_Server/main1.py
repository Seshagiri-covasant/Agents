# --- mcp_agent1.py ---
from mcp.server.fastmcp import FastMCP
from io import StringIO
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import os
import uuid
import sys
import datetime
import json

matplotlib.use('Agg')  

mcp = FastMCP("CSV Tool Server")

# --- Tool 1: Analyze CSV ---
@mcp.tool()
def analyse_data(csv_text: str) -> str:
    try:
        df = pd.read_csv(StringIO(csv_text))
        description = df.describe(include="all").to_string()
        head = df.head().to_string()
        buffer = StringIO()
        df.info(buf=buffer)
        info = buffer.getvalue()

        return f"--- Data Description ---\n{description}\n\n--- Head ---\n{head}\n\n--- Info ---\n{info}"
    except Exception as e:
        return f"[ERROR] Analysis failed: {e}"

# --- Tool 2: Plot Graph ---
@mcp.tool(name="plot_graph", description="Create a PNG line plot from all numeric columns in the CSV file.")
def plot_graph(csv_text: str) -> str:
    try:
        df = pd.read_csv(StringIO(csv_text))
        numeric_cols = df.select_dtypes(include=np.number).columns

        if numeric_cols.empty:
            return "[ERROR] No numeric columns found to plot."

        plt.figure(figsize=(12, 6))
        for col in numeric_cols:
            plt.plot(df.index, df[col], label=col, marker='o')

        plt.title("CSV Numeric Data")
        plt.xlabel("Index")
        plt.ylabel("Values")
        plt.legend()
        plt.tight_layout()

        plot_dir = os.path.join(os.path.dirname(__file__), "saved_plots")
        os.makedirs(plot_dir, exist_ok=True)

        filename = f"plot_{uuid.uuid4().hex}.png"
        filepath = os.path.join(plot_dir, filename)

        plt.savefig(filepath, bbox_inches='tight')
        plt.clf()

        if os.path.exists(filepath):
            return f"PLOT_READY::{filename}"
        else:
            return "[ERROR] Plot file was not created."

    except Exception as e:
        return f"[ERROR] Plotting failed: {e}"
    finally:
        plt.close('all')



# --- Tool 3: Calendar Scheduler ---
@mcp.tool()
def calendar_scheduler(date: str, time: str, event: str) -> str:
    try:
        dt = datetime.datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        return f" Event '{event}' scheduled on {dt.strftime('%A, %d %B %Y at %I:%M %p')}"
    except Exception as e:
        return f"[ERROR] Failed to schedule event: {e}"

# --- Tool 4: Report Generator ---
@mcp.tool()
def report_generator(data: str, title: str = "Analysis Report") -> str:
    try:
        filename = f"report_{uuid.uuid4().hex}.txt"
        report_dir = os.path.join(os.path.dirname(__file__), "saved_reports")
        os.makedirs(report_dir, exist_ok=True)
        filepath = os.path.join(report_dir, filename)

        with open(filepath, "w") as f:
            f.write(f"{title}\n{'=' * len(title)}\n\n{data}")

        return f" Report saved as '{filename}' in folder 'saved_reports/'"
    except Exception as e:
        return f"[ERROR] Report generation failed: {e}"

if __name__ == "__main__":
    print(" Starting CSV MCP Tool Server...")
    print("Python version:", sys.version)
    plot_path = os.path.join(os.path.dirname(__file__), "saved_plots")
    os.makedirs(plot_path, exist_ok=True)
    report_path = os.path.join(os.path.dirname(__file__), "saved_reports")
    os.makedirs(report_path, exist_ok=True)
    print(f"Saved plots directory: {plot_path}")
    print(f"Saved reports directory: {report_path}")
    mcp.start()
