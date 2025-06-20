# Advanced Conversational AI Agent with Dynamic Tools

This project is a sophisticated, full-stack conversational AI agent built with Python, FastAPI, and React. It demonstrates a modern architecture where a central AI agent can dynamically use a variety of tools to answer questions, analyze data, and interact with external services.

## ✨ Core Features

*   **Conversational Memory:** The chatbot remembers previous turns in a conversation, allowing for natural, contextual follow-up questions.
*   **Dynamic Tool Use:** The agent is not hard-coded. It dynamically decides which tool to use based on the user's request.
    *   **Real-time Weather:** Fetches current weather conditions for any location using an external API.
    *   **File Analysis & Plotting:** Users can upload CSV or Excel files. The agent can analyze this data, provide summaries (row/column counts, etc.), and generate plots (line, histogram, scatter) on demand.
    *   **(Optional RAG) Knowledge Base:** Can be extended with a RAG (Retrieval-Augmented Generation) pipeline to answer questions based on a specific set of documents (e.g., company knowledge base, research papers).
*   **Persistent Chat History:** Conversations are saved to a MongoDB database. Users can see their past conversations in a sidebar, click to load them, and continue where they left off.
*   **Streaming Responses:** AI responses and tool events are streamed in real-time to the frontend for a smooth, interactive user experience.
*   **Model Agnostic:** Uses **LiteLLM** as a universal adapter, allowing the agent to be powered by over 100 different LLMs (including models from Google, OpenAI, Anthropic, Mistral, and open-source models) just by changing an environment variable.
*   **Modular Architecture:** The system is cleanly separated into three main components: a React frontend, a FastAPI backend (Chatbot API), and a separate FastAPI server for tools (MCP Server).

## 🏛️ System Architecture

The project consists of three independent but interconnected services:

1.  **Frontend (React)**
    *   Provides the user interface for the chat.
    *   Manages the display of messages, the chat history sidebar, and file uploads.
    *   Communicates with the Chatbot API via HTTP requests and Server-Sent Events (SSE) for streaming.

2.  **Chatbot API (`chatbot_api_main.py`)**
    *   The main backend built with FastAPI.
    *   Handles all user requests from the frontend.
    *   Manages user sessions and conversation history in MongoDB.
    *   Contains the core agent logic (`mcp_agent_langchain.py`), which orchestrates calls to the LLM and the MCP Tool Server.

3.  **MCP (Multi-Capability Provider) Tool Server (`example_mcp_server.py`)**
    *   A separate FastAPI server that hosts the agent's "tools."
    *   Exposes endpoints for specific capabilities like fetching weather, analyzing a data file, or performing a RAG search.
    *   This modular design allows new tools to be added or updated independently without affecting the main chatbot application.

### Workflow for a Tool-Based Request

1.  A user asks, "What's the weather like in Paris?"
2.  The **Frontend** sends this message to the **Chatbot API**.
3.  The **Agent** within the API receives the message. It has been pre-initialized with a list of available tools fetched from the **MCP Server**.
4.  The Agent sends the user's question and the tool descriptions to the **LLM (via LiteLLM)**.
5.  The LLM reasons that the `get_weather` tool is appropriate and returns a structured request to call it with `location: "Paris"`.
6.  The Agent executes this by making an API call to the `get_weather` endpoint on the **MCP Server**.
7.  The **MCP Server** calls the OpenWeatherMap API and returns the weather data.
8.  The Agent receives this data and makes a *second* call to the **LLM**, providing the original question and the new weather data.
9.  The LLM formulates a natural language response (e.g., "The weather in Paris is currently...").
10. The **Agent** streams this final response back to the **Frontend**.

## 🚀 Getting Started

### Prerequisites

*   Python 3.10+
*   Node.js and npm (for the React frontend)
*   MongoDB instance (local or cloud)
*   API keys for an LLM provider (e.g., Google for Gemini, OpenAI, etc.)
*   API key for OpenWeatherMap

### Backend Setup

1.  **Clone the repository:**
    ```bash
    git clone <your-repository-url>
    cd <your-repository-url>
    ```

2.  **Set up a virtual environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

3.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *Note: Your `requirements.txt` should include `fastapi`, `uvicorn`, `python-dotenv`, `langchain`, `langchain-community`, `litellm`, `motor`, `pymongo`, `httpx`, `pandas`, `matplotlib`, `pydantic`, `sse-starlette`, and any other required packages.*

4.  **Create a `.env` file** in the root directory and add your configuration:
    ```env
    # --- API Keys ---
    GOOGLE_API_KEY="your-google-api-key"
    OPENAI_API_KEY="your-openai-api-key" # (if you use OpenAI models)
    WEATHERMAP_API_KEY="your-openweathermap-api-key"

    # --- Service Configuration ---
    # The model name should be in LiteLLM format (e.g., provider/model)
    GEMINI_MODEL_NAME="gemini/gemini-1.5-flash-latest"
    MCP_SERVER_URL="http://localhost:8000"

    # --- Database Configuration ---
    MONGO_URI="mongodb://localhost:27017/"
    MONGO_DB_NAME="chat_app_db"
    LANGCHAIN_MONGO_COLLECTION_NAME="mcp_history_langchain"
    ```

5.  **Run the Servers:**
    *   Open two separate terminals.
    *   In the first terminal, start the MCP Tool Server:
        ```bash
        python example_mcp_server.py
        ```
    *   In the second terminal, start the main Chatbot API:
        ```bash
        python chatbot_api_main.py
        ```

### Frontend Setup

1.  **Navigate to the frontend directory:**
    ```bash
    cd frontend # Or your frontend's directory name
    ```

2.  **Install dependencies:**
    ```bash
    npm install
    ```

3.  **Start the React development server:**
    ```bash
    npm start
    ```

4.  Open your browser and navigate to `http://localhost:3000`. You should now be able to interact with your chatbot.

## 🛠️ Future Enhancements

*   **Add More Tools:** The architecture makes it easy to add new tools (e.g., web search, database queries, calendar integration) by simply adding a new function and schema to the MCP server.
*   **User Authentication:** Implement a login system to support multiple users with their own private chat histories.
*   **Dynamic RAG:** Build a UI for administrators to upload, manage, and delete documents for the RAG knowledge base in real-time.
*   **Deployment:** Containerize the services using Docker for easy deployment.
