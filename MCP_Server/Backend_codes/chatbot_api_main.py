# File: chatbot_api_main.py
# Updated to work with the revised MCPAgentSSE

import json
import os
import shutil
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone # Not directly used here but good for context
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator, Tuple # Corrected Tuple import

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse # For SSE
from fastapi.middleware.cors import CORSMiddleware
from pymongo import ASCENDING, DESCENDING

# Assuming these are in the same directory or Python path
from logger_config import log # Your custom logger
from mcp_agent_mongodb import MCPAgentSSE, NEW_CHAT_PLACEHOLDER_PREFIX # Import from your agent file

# --- ENVIRONMENT VARIABLES & SETUP ---
# Ensure these are loaded, e.g., from a .env file if you use python-dotenv
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000")
LITELLM_MODEL_NAME = os.getenv("LITELLM_MODEL_NAME", "gemini/gemini-1.5-flash") # Renamed for clarity vs. LITELLM_MODEL
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "chat_app_db")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "mcp_history")


# Global agent instance
agent_instance: Optional[MCPAgentSSE] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_instance
    log.info("Chatbot API: Lifespan event - Initializing...")
    try:
        log.info(f"Chatbot API: MCP_SERVER_URL='{MCP_SERVER_URL}', LITELLM_MODEL_NAME='{LITELLM_MODEL_NAME}', MONGO_URI='{MONGO_URI[:20]}...'")
        agent_instance = MCPAgentSSE(
            mcp_server_url=MCP_SERVER_URL,
            model=LITELLM_MODEL_NAME,
            mongo_uri=MONGO_URI,
            mongo_db_name=MONGO_DB_NAME,
            mongo_collection_name=MONGO_COLLECTION_NAME
        )
        await agent_instance.initialize_async_components() # Crucial async initialization
        log.info("Chatbot API: MCPAgentSSE Initialization complete.")
    except Exception as e:
        log.critical(f"Chatbot API: CRITICAL - Failed to initialize MCPAgentSSE during startup: {e}\n{traceback.format_exc()}")
        agent_instance = None # Ensure it's None if init fails
    
    yield # API is ready to serve
    
    log.info("Chatbot API: Lifespan event - Shutting down.")
    if agent_instance and agent_instance.mongo_client:
        try:
            agent_instance.mongo_client.close() # Close Motor client
            log.info("Chatbot API: MongoDB connection closed.")
        except Exception as e:
            log.error(f"Chatbot API: Error closing MongoDB connection: {e}")

app = FastAPI(
    title="Chatbot API with MCPAgentSSE",
    version="2.3.0", # Bump version
    lifespan=lifespan
)

# --- CORS MIDDLEWARE ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- TEMPORARY UPLOAD DIRECTORY ---
TEMP_UPLOAD_DIR = Path("temp_uploads_api")
TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True) # Ensure it exists

# --- HELPER FUNCTIONS ---
def get_resolved_conversation_id(
    client_session_id: Optional[str], 
    provided_daily_conversation_id: Optional[str]
) -> Tuple[str, bool]:
    """
    Determines the conversation ID to use.
    If provided_daily_conversation_id is a placeholder or None, generates a new ID.
    Returns the resolved ID and a boolean indicating if it's a new conversation.
    """
    is_new_conversation = False
    if not provided_daily_conversation_id or \
       provided_daily_conversation_id.startswith(NEW_CHAT_PLACEHOLDER_PREFIX):
        # Generate a new, unique conversation ID
        # Using a simpler prefix as daily_conversation_id is a unique concept here
        new_id = f"conv_d_{uuid.uuid4().hex}" 
        log.info(f"API: New conversation started for client '{client_session_id}'. Assigned DailyConversationID: '{new_id}'")
        is_new_conversation = True
        return new_id, is_new_conversation
    
    log.debug(f"API: Continuing existing conversation for client '{client_session_id}'. DailyConversationID: '{provided_daily_conversation_id}'")
    return provided_daily_conversation_id, is_new_conversation

async def stream_agent_response(
    resolved_daily_conv_id: str, 
    client_session_id: str, 
    user_message: str, 
    is_new_conversation: bool
) -> AsyncGenerator[str, None]:
    """
    Streams responses from the MCPAgentSSE in SSE format.
    Each yielded item from the agent (which is a dict) is JSON-stringified and wrapped.
    """
    if not agent_instance:
        log.error("API stream_agent_response: Agent not initialized!")
        error_payload = json.dumps({"type": "error", "content": "Chat agent is not available. Please try again later."})
        yield f"data: {error_payload}\n\n"
        return

    first_event_sent = False
    try:
        # The agent's chat_streaming now yields dictionaries
        async for event_dict in agent_instance.chat_streaming(
            user_message=user_message,
            resolved_daily_conv_id=resolved_daily_conv_id,
            client_session_id=client_session_id
        ):
            if not isinstance(event_dict, dict):
                log.warning(f"API stream_agent_response: Agent yielded non-dict item: {event_dict}")
                continue

            # If it's a new conversation and this is the first event,
            # inject the confirmed conversation_id into the payload for the client.
            if is_new_conversation and not first_event_sent:
                event_dict["daily_conversation_id"] = resolved_daily_conv_id # Send the actual ID back
                log.info(f"API stream_agent_response: Injected daily_conversation_id '{resolved_daily_conv_id}' for new chat.")
            
            # SSE format: data: <json_string>\n\n
            try:
                json_payload = json.dumps(event_dict)
                yield f"data: {json_payload}\n\n"
                first_event_sent = True # Mark after successfully sending the first event
            except TypeError as te: # Handle potential JSON serialization errors
                log.error(f"API stream_agent_response: JSON serialization error for event_dict: {event_dict}. Error: {te}")
                error_event = json.dumps({"type": "error", "content": f"Agent stream error: Malformed data. {str(te)}"})
                yield f"data: {error_event}\n\n"
                
    except Exception as e:
        log.error(f"API stream_agent_response: Error during agent streaming for conv '{resolved_daily_conv_id}': {e}\n{traceback.format_exc()}")
        error_payload = json.dumps({"type": "error", "content": f"A critical error occurred in the chat stream: {str(e)}"})
        yield f"data: {error_payload}\n\n"
    finally:
        log.debug(f"API stream_agent_response: Streaming finished for conv '{resolved_daily_conv_id}'.")



@app.post("/chat_stream")
async def chat_stream_endpoint(request: Request):
    """
    Handles streaming chat requests.
    Receives user message, client session ID, and potentially a daily_conversation_id.
    """
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        log.warning("API /chat_stream: Invalid JSON payload received.")
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    user_message = payload.get("message")
    client_session_id = payload.get("client_session_id")
    # Frontend sends 'conversation_id', but internally we call it 'daily_conversation_id'
    provided_daily_conv_id = payload.get("conversation_id") 

    if not user_message or not client_session_id:
        log.warning(f"API /chat_stream: Missing message or client_session_id. Payload: {payload}")
        raise HTTPException(status_code=400, detail="Missing 'message' or 'client_session_id'.")

    # Get the actual conversation ID to use (new or existing)
    resolved_id, is_new_conv = get_resolved_conversation_id(client_session_id, provided_daily_conv_id)
    
    log.info(f"API /chat_stream: Request for ConvID '{resolved_id}' (New: {is_new_conv}), ClientSID '{client_session_id}'. Message: '{user_message[:50]}...'")

    return StreamingResponse(
        stream_agent_response(
            resolved_daily_conv_id=resolved_id,
            client_session_id=client_session_id,
            user_message=user_message,
            is_new_conversation=is_new_conv
        ),
        media_type="text/event-stream"
    )

@app.get("/history/summary_list")
async def get_history_summary_list(client_session_id: str = Query(..., min_length=1)):
    log.debug(f"API /history/summary_list: ENTERED for ClientSID '{client_session_id}'.")
    if agent_instance:
        log.debug(f"API /history/summary_list: agent_instance exists. history_collection type: {type(agent_instance.history_collection)}, is None: {agent_instance.history_collection is None}")
    else:
        log.error("API /history/summary_list: agent_instance is None at point of check!")

    if not agent_instance or agent_instance.history_collection is None: 
        log.error("API /history/summary_list: Condition failed: Agent or history_collection not initialized.") # This is your current error log
        raise HTTPException(status_code=503, detail="History service is temporarily unavailable.")
    log.debug(f"API /history/summary_list: Request for ClientSID '{client_session_id}'.")
    
    # Aggregation pipeline to get unique conversations and their first user message as title
    pipeline = [
        {"$match": {"client_session_id": client_session_id, "role": "user"}}, # Consider only user messages for titles
        {"$sort": {"timestamp": ASCENDING}}, # Sort by time to get the first message reliably
        {
            "$group": {
                "_id": "$daily_conversation_id", # Group by conversation
                "first_user_message_content": {"$first": "$content"}, # Get the content of the first user message
                "last_timestamp": {"$max": "$timestamp"} # Get the timestamp of the latest message in the conversation for sorting
            }
        },
        {"$match": {"first_user_message_content": {"$ne": None}}}, # Ensure we have content for the title
        {"$sort": {"last_timestamp": DESCENDING}}, # Sort conversations by most recent activity
        {
            "$project": {
                "_id": 0, # Exclude the default MongoDB _id
                "id": "$_id", # Rename _id (daily_conversation_id) to "id" for frontend
                # Create title: take first 40 chars of the first user message.
                # Assumes content is a string. Agent now saves user message content as string.
                "title": {"$substrCP": ["$first_user_message_content", 0, 40]},
                "timestamp": "$last_timestamp" # Include timestamp for potential client-side sorting/display
            }
        },
        {"$limit": 100} # Limit the number of history items returned
    ]
    try:
        cursor = agent_instance.history_collection.aggregate(pipeline)
        summary_list = await cursor.to_list(length=100) # Max 100 history items
        log.info(f"API /history/summary_list: Found {len(summary_list)} history items for ClientSID '{client_session_id}'.")
        return summary_list
    except Exception as e:
        log.error(f"API /history/summary_list: DB error for ClientSID '{client_session_id}': {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error fetching history summary: {str(e)}")


@app.get("/history/conversation_by_id")
async def get_conversation_by_id(conversation_id: str = Query(..., min_length=1)):
    log.debug(f"API /history/conversation_by_id: ENTERED for ConvID '{conversation_id}'.")
    if agent_instance:
        log.debug(f"API /history/conversation_by_id: agent_instance exists. history_collection type: {type(agent_instance.history_collection)}, is None: {agent_instance.history_collection is None}")
    else:
        log.error("API /history/conversation_by_id: agent_instance is None at point of check!")

    if not agent_instance or agent_instance.history_collection is None:
        log.error("API /history/conversation_by_id: Condition failed: Agent or history_collection not initialized.") # This is your current error log
        raise HTTPException(status_code=503, detail="History service is temporarily unavailable.")

    log.debug(f"API /history/conversation_by_id: Request for ConvID '{conversation_id}'.")
    
    try:
        # Fetch messages, sort by timestamp
        cursor = agent_instance.history_collection.find(
            {"daily_conversation_id": conversation_id}
        ).sort("timestamp", ASCENDING).limit(200) # Limit messages per conversation
        
        messages_from_db = await cursor.to_list(length=200)
        
        # Convert MongoDB ObjectId to string for JSON serialization
        processed_messages = []
        for msg in messages_from_db:
            msg["_id"] = str(msg["_id"]) # Convert ObjectId
            processed_messages.append(msg)
            
        log.info(f"API /history/conversation_by_id: Found {len(processed_messages)} messages for ConvID '{conversation_id}'.")
        return {"messages": processed_messages} # Return in the format expected by frontend
    except Exception as e:
        log.error(f"API /history/conversation_by_id: DB error for ConvID '{conversation_id}': {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error fetching conversation: {str(e)}")


@app.post("/upload_for_agent")
async def upload_file_for_agent_endpoint(
    session_id: str = Form(...), # This is client_session_id from frontend
    file: UploadFile = File(...)
):
    """
    Handles file uploads, passes them to the agent for processing via MCP.
    """
    if not agent_instance:
        log.error("API /upload_for_agent: Agent not initialized.")
        raise HTTPException(status_code=503, detail="File processing service (agent) is not available.")

    # Secure filename and create a temporary path
    # Sanitize filename (though UploadFile.filename should be somewhat safe)
    base_filename = "".join(c if c.isalnum() or c in ['.', '_', '-'] else '_' for c in Path(file.filename).name)
    if not base_filename: base_filename = "uploaded_file" # Default if all chars are stripped
    
    temp_file_path = TEMP_UPLOAD_DIR / f"{session_id}_{uuid.uuid4().hex[:8]}_{base_filename}"
    
    log.info(f"API /upload_for_agent: Received file '{file.filename}' for ClientSID '{session_id}'. Temp path: '{temp_file_path}'.")

    try:
        # Save uploaded file to the temporary path
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        log.debug(f"API /upload_for_agent: File '{temp_file_path}' saved temporarily.")

        # Call agent's upload_file method (which then calls MCP server)
        # The agent's upload_file expects client_session_id
        upload_result = await agent_instance.upload_file(
            file_path=str(temp_file_path),
            file_name=file.filename, # Original filename
            file_content_type=file.content_type,
            client_session_id=session_id # Pass client_session_id to agent
        )

        if upload_result.get("success"):
            log.info(f"API /upload_for_agent: Agent processed file successfully for ClientSID '{session_id}'. MCP Response: {upload_result.get('data')}")
            # Return what frontend needs: message, mcp_file_path, original_filename
            return {
                "message": upload_result.get("data", {}).get("message", "File processed by agent."),
                "mcp_file_path": upload_result.get("data", {}).get("file_path"), # Path on MCP server
                "original_filename": file.filename
            }
        else:
            error_detail = upload_result.get('error', 'Unknown error during agent file processing.')
            log.error(f"API /upload_for_agent: Agent failed to process file for ClientSID '{session_id}'. Error: {error_detail}")
            raise HTTPException(status_code=500, detail=f"File processing by agent failed: {error_detail}")

    except HTTPException: # Re-raise HTTPExceptions
        raise
    except Exception as e:
        log.error(f"API /upload_for_agent: Unexpected error for ClientSID '{session_id}', File '{file.filename}': {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during file upload: {str(e)}")
    finally:
        # Clean up the temporary file
        if temp_file_path.exists():
            try:
                os.remove(temp_file_path)
                log.debug(f"API /upload_for_agent: Temporary file '{temp_file_path}' removed.")
            except OSError as oe:
                log.warning(f"API /upload_for_agent: Could not remove temporary file '{temp_file_path}'. Error: {oe}")
        if file:
            await file.close() # Ensure file stream is closed

# In chatbot_api_main.py
# ...
# File: chatbot_api_main.py

# ... (imports, app setup, other endpoints) ...

@app.post("/clear_file_context")
async def clear_file_context_endpoint(request: Request): # This endpoint itself is async
    try:
        payload = await request.json()
    except json.JSONDecodeError: # Ensure json is imported
        log.warning("API /clear_file_context: Invalid JSON payload.")
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        
    client_session_id = payload.get("client_session_id")

    if not client_session_id:
        log.warning("API /clear_file_context: client_session_id missing from payload.")
        raise HTTPException(status_code=400, detail="client_session_id is required.")
    
    if not agent_instance: # Check if agent_instance itself is None
        log.error("API /clear_file_context: Agent instance is not available.")
        raise HTTPException(status_code=503, detail="Agent service is not available.")

    log.info(f"API /clear_file_context: Request to clear context for ClientSID '{client_session_id}'.")
    
    file_info_to_delete = None
    if client_session_id in agent_instance.last_uploaded_files:
        file_info_to_delete = agent_instance.last_uploaded_files.get(client_session_id, {}).copy() 

    # --- THIS IS THE CORRECTED CALL ---
    # Call the correctly named synchronous method on the agent instance. NO await.
    was_cleared = agent_instance.clear_last_uploaded_file_context(client_session_id)
    # --- END OF CORRECTION ---

    mcp_deletion_success = False
    if was_cleared and file_info_to_delete and file_info_to_delete.get("path"):
        mcp_file_path_to_delete = file_info_to_delete.get("path")
        log.info(f"API /clear_file_context: Agent context cleared. Requesting deletion of MCP file: {mcp_file_path_to_delete}")
        # agent_instance.delete_file_on_mcp_server is an async method, so it needs await
        mcp_deletion_success = await agent_instance.delete_file_on_mcp_server(mcp_file_path_to_delete)
        log.info(f"API /clear_file_context: MCP file deletion attempt result: {mcp_deletion_success}")
    elif was_cleared:
        log.info(f"API /clear_file_context: Agent context cleared, but no specific MCP file path was found in context to delete on MCP server.")

    if was_cleared:
        return {"message": "File context cleared successfully from agent.", "mcp_file_deleted_status": mcp_deletion_success}
    else:
        log.info(f"API /clear_file_context: No active file context found to clear for ClientSID '{client_session_id}'.")
        return {"message": "No active file context found in agent to clear."}

# ... (rest of your API code)
if __name__ == "__main__":
    # This allows running directly with uvicorn for development
    # Ensure environment variables are loaded if you use a .env file (e.g., via `python-dotenv` in this script or uvicorn --env-file)
    # from dotenv import load_dotenv
    # load_dotenv()
    import uvicorn
    log.info("Starting Chatbot API directly with Uvicorn...")
    uvicorn.run("__main__:app", host="0.0.0.0", port=8080, reload=True)
