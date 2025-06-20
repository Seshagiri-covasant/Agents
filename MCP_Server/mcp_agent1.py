from flask import Flask, request, jsonify, send_from_directory
from langchain.agents import Tool, initialize_agent
from langchain.agents.agent_types import AgentType
from langchain_mistralai.chat_models import ChatMistralAI
import requests
import os
from dotenv import load_dotenv

load_dotenv()
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

app = Flask(__name__)

llm = ChatMistralAI(
    model="mistral-small",
    temperature=0.5,
    mistral_api_key=MISTRAL_API_KEY
)

PLOT_DIR = os.path.join(os.path.dirname(__file__), "saved_plots")
REPORT_DIR = os.path.join(os.path.dirname(__file__), "saved_reports")
os.makedirs(PLOT_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

def call_mcp_tool(tool_name, data):
    try:
        res = requests.post(f"http://localhost:6274/tools/{tool_name}/invoke", json=data)
        res_json = res.json()
        output = res_json.get("output", "No output returned")

        # --- Patch for plot/report tool output ---
        if tool_name == "plot_graph" and "saved_plots" in output:
            filename = output.split("/")[-1]
            return f"PLOT_READY::{filename}"
        elif tool_name == "report_generator" and "saved_reports" in output:
            filename = output.split("/")[-1]
            return f"REPORT_READY::{filename}"

        return output
    except Exception as e:
        return f"[ERROR] MCP call failed: {e}"

analyse_data_tool = Tool(
    name="analyse_data",
    func=lambda csv: call_mcp_tool("analyse_data", {"csv_text": csv}),
    description="Analyzes CSV data and returns statistics, head, and info.",
    return_direct=True
)

plot_graph_tool = Tool(
    name="plot_graph",
    func=lambda csv: call_mcp_tool("plot_graph", {"csv_text": csv}),
    description="Plots numeric columns from CSV and saves as PNG.",
    return_direct=True
)

calendar_scheduler_tool = Tool(
    name="calendar_scheduler",
    func=lambda args: call_mcp_tool("calendar_scheduler", {
        "date": args.get("date", ""),
        "time": args.get("time", ""),
        "event": args.get("event", "")
    }),
    description="Schedules an event. Provide: date (YYYY-MM-DD), time (HH:MM), and event title.",
    return_direct=True
)

report_generator_tool = Tool(
    name="report_generator",
    func=lambda args: call_mcp_tool("report_generator", {
        "data": args.get("data", ""),
        "title": args.get("title", "Analysis Report")
    }),
    description="Generates a TXT report file with a given title and content.",
    return_direct=True
)

agent = initialize_agent(
    tools=[
        analyse_data_tool,
        plot_graph_tool,
        calendar_scheduler_tool,
        report_generator_tool
    ],
    llm=llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True,
    handle_parsing_errors=True
)

@app.route("/query", methods=["POST"])
def handle_query():
    try:
        question = request.form.get("question")
        file = request.files.get("file")

        if not question:
            return jsonify({"error": "Missing 'question' parameter"}), 400
        if not file:
            return jsonify({"error": "Missing file upload"}), 400

        csv_text = file.read().decode('utf-8')

        prompt = (
            f"You are a CSV data assistant.\n"
            f"Here is the CSV data:\n{csv_text}\n"
            f"Question: {question}\n"
            f"Use the tools available to analyze, plot, schedule, or report."
        )

        response = agent.run(prompt)

        # Handle special tool outputs
        if isinstance(response, str):
            if response.startswith("PLOT_READY::"):
                filename = response.split("::")[1]
                return jsonify({
                    "response": " Plot created.",
                    "plot_url": f"/saved_plots/{filename}"
                })
            elif response.startswith("REPORT_READY::"):
                filename = response.split("::")[1]
                return jsonify({
                    "response": " Report generated.",
                    "report_url": f"/saved_reports/{filename}"
                })

        return jsonify({"response": response})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Serve Plot Files ---
@app.route('/saved_plots/<filename>')
def serve_plot(filename):
    return send_from_directory(PLOT_DIR, filename)

# --- Serve Report Files ---
@app.route('/saved_reports/<filename>')
def serve_report(filename):
    return send_from_directory(REPORT_DIR, filename)

if __name__ == "__main__":
    app.run(port=5000, debug=True)
