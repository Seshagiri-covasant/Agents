from flask import Flask, request, jsonify
import os
import json
import litellm
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient

app = Flask(__name__)

# LiteLLM model setup
litellm.model_alias_map = {
    "gemini": "gemini/gemini-1.5-flash"
}

# MCP client using SSE
mcp_client = MultiServerMCPClient({
    "tools_mcp": {
        "url": "http://localhost:8000/sse",
        "transport": "sse"
    }
})

# Tool definition
tool_schema = [
    {
        "type": "function",
        "name": "get_weather",
        "description": "Get current temperature for a given location.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City and country e.g. Bogotá, Colombia"
                }
            },
            "required": ["location"],
            "additionalProperties": False
        }
    }
]
tool_choice={"type": "function", "function": {"name": "get_weather"}}

# System prompt
system_prompt = """
You are a helpful assistant.

If the user's question requires external, real-time, or non-static information (like weather), call the appropriate tool. Otherwise, answer directly.

You have access to the following tool:

- get_weather: Use this to get the current temperature of a city. Only call it if the user asks about current or real-time weather in a specific city.

Always respond accurately, and never fabricate weather data yourself.
"""


@app.route("/query", methods=["POST"])
def handle_query():
    user_question = request.json.get("question")
    if not user_question:
        return jsonify({"error": "Missing 'question'"}), 400

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_question}
    ]

    while True:
        response = litellm.completion(
            model="gemini",
            messages=messages,
            tools=tool_schema,
            tool_choice="auto",
            temperature=0.3,
            stream=False
        )["choices"][0]["message"]
        print("LLM RESPONSE:", response)

        if "tool_calls" in response:
            tool_call = response["tool_calls"][0]
            tool_name = tool_call["function"]["name"]
            tool_args = json.loads(tool_call["function"]["arguments"])

            try:
                # Directly run the async astream_tool using asyncio
                async def call_tool():
                    stream = await mcp_client.astream_tool("tools_mcp", tool_name, tool_args)
                    return "".join([chunk async for chunk in stream])

                tool_result = asyncio.run(call_tool())
            except Exception as e:
                tool_result = f"Error calling tool: {str(e)}"

            messages.append({"role": "assistant", "tool_calls": [tool_call]})
            messages.append({"role": "tool", "name": tool_name, "content": tool_result})
        else:
            return jsonify({"answer": response.get("content", "No answer.")})

if __name__ == "__main__":
    app.run(port=5000, debug=True)
