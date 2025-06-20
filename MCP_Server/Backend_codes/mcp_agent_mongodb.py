# File: mcp_agent_mongodb.py
# Merged and Refined Version

import asyncio
import json
import os
import traceback
from typing import List, Dict, Any, Optional, AsyncGenerator
from pathlib import Path
from datetime import datetime, timezone, timedelta

import litellm
from litellm import acompletion, ModelResponse
import litellm.exceptions 
import httpx # For async HTTP requests
import aiohttp # For streaming from MCP tool server
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo import ASCENDING, DESCENDING

# --- CONSTANTS ---
NEW_CHAT_PLACEHOLDER_PREFIX = "new_chat_placeholder_"
# PENDING_INIT_CONVO_ID = "pending_initialization" # Not strictly needed if frontend handles new chat ID correctly

# --- LITELLM VERBOSITY ---
if hasattr(litellm, 'set_verbose') and callable(litellm.set_verbose):
    litellm.set_verbose = True # Preferred way if available
else:
    os.environ['LITELLM_LOG'] = 'DEBUG' # Fallback
    print("LiteLLM: Using LITELLM_LOG environment variable for verbosity.")

class MCPAgentSSE:
    def __init__(self, mcp_server_url: str, model: str, mongo_uri: str,
                 mongo_db_name: str = "chat_app_db",
                 mongo_collection_name: str = "mcp_history"):
        self.mcp_server_url = mcp_server_url.rstrip('/')
        self.model = model
        self.tools: List[Dict[str, Any]] = [] # For LiteLLM
        self.mongo_uri = mongo_uri
        self.mongo_db_name = mongo_db_name
        self.mongo_collection_name = mongo_collection_name
        
        self.mongo_client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[Any] = None # Will be AsyncIOMotorDatabase
        self.history_collection: Optional[AsyncIOMotorCollection] = None
        
        self.last_uploaded_files: Dict[str, Dict[str, Any]] = {} # client_session_id -> {path, original_filename, timestamp}
        print(f"Agent: Initialized. MCP URL: {self.mcp_server_url}, Model: {self.model}")

    async def initialize_async_components(self):
        """Connects to DB and loads tools. Must be called after instantiation."""
        print("Agent: Starting asynchronous component initialization...")
        await self._initialize_mongodb()
        await self.load_tools_from_mcp() # Renamed for clarity
        print("Agent: Asynchronous component initialization complete.")

    async def _initialize_mongodb(self):
        try:
            print(f"Agent: Initializing MongoDB connection to {self.mongo_uri}...")
            self.mongo_client = AsyncIOMotorClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
            await self.mongo_client.admin.command('ismaster') # Verify connection
            self.db = self.mongo_client[self.mongo_db_name]
            self.history_collection = self.db[self.mongo_collection_name]
            
            if self.history_collection is not None:
                # Indexes for common queries
                await self.history_collection.create_index([("daily_conversation_id", ASCENDING), ("timestamp", ASCENDING)])
                await self.history_collection.create_index([("client_session_id", ASCENDING), ("timestamp", DESCENDING)])
            print(f"Agent: Successfully connected to MongoDB: {self.mongo_db_name}/{self.mongo_collection_name}")
        except Exception as e:
            print(f"Agent: CRITICAL - Error connecting to MongoDB ({self.mongo_uri}): {e}\n{traceback.format_exc()}")
            self.mongo_client = None; self.db = None; self.history_collection = None

    async def load_tools_from_mcp(self):
        """Asynchronously fetches tool schemas from the MCP server and formats them for LiteLLM."""
        try:
            if not self.mcp_server_url or self.mcp_server_url == "http://localhost:0000": # Basic check
                print("Agent: MCP_SERVER_URL is not set or invalid. Cannot load tools."); self.tools = []; return

            tools_url = f"{self.mcp_server_url}/tools"
            print(f"Agent: Loading tools from MCP: {tools_url}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(tools_url)
                response.raise_for_status() # Raise an exception for bad status codes
                data = response.json()
            
            raw_tool_schemas_from_mcp = data.get("tools", [])
            formatted_tools_for_litellm: List[Dict[str, Any]] = []
            if raw_tool_schemas_from_mcp:
                for mcp_tool_schema in raw_tool_schemas_from_mcp:
                    if "name" in mcp_tool_schema and "parameters" in mcp_tool_schema:
                        # LiteLLM expects: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
                        function_definition = {
                            "name": mcp_tool_schema["name"],
                            "description": mcp_tool_schema.get("description", f"Tool named {mcp_tool_schema['name']}"),
                            "parameters": mcp_tool_schema["parameters"]
                        }
                        formatted_tools_for_litellm.append({"type": "function", "function": function_definition})
                    else:
                        print(f"Agent: Warning - Skipping tool from MCP with unexpected schema: {json.dumps(mcp_tool_schema)}")
            
            self.tools = formatted_tools_for_litellm
            if not self.tools:
                print(f"Agent: No valid tools loaded/formatted from MCP server ({tools_url}). Tool usage will be disabled.")
            else:
                tool_names = [t['function']['name'] for t in self.tools if t.get('function') and t['function'].get('name')]
                print(f"Agent: Loaded and formatted tools for LiteLLM: {tool_names}")
        except httpx.RequestError as e:
            print(f"Agent: HTTP Error loading tools from {self.mcp_server_url}: {e}\n{traceback.format_exc()}"); self.tools = []
        except Exception as e:
            print(f"Agent: Unexpected error loading tools: {e}\n{traceback.format_exc()}"); self.tools = []

    async def save_message_to_db(self, daily_conversation_id: str, role: str, content: Any,
                                 client_session_id: Optional[str], # Made optional to align with some calls
                                 tool_calls: Optional[List[Any]] = None, # For assistant's decision to call tools
                                 tool_call_id: Optional[str] = None, # For tool's own response
                                 name: Optional[str] = None): # For tool's own response (function name)
        if self.history_collection is None:
            print("Agent: DB collection is None, cannot save message."); return
        
        # Prevent saving for placeholder/pending IDs
        if not daily_conversation_id or daily_conversation_id.startswith(NEW_CHAT_PLACEHOLDER_PREFIX):
            print(f"Agent: Skipping DB save for placeholder daily_id: '{daily_conversation_id}'"); return

        message_doc: Dict[str, Any] = {
            "daily_conversation_id": daily_conversation_id,
            "client_session_id": client_session_id,
            "timestamp": datetime.now(timezone.utc),
            "role": role,
            "content": content # This can be string, or structured dict for tool outputs
        }
        
        # Serialize tool_calls if provided (from assistant message)
        if tool_calls:
            serialized_tool_calls: List[Dict[str, Any]] = []
            for tc in tool_calls: # tc is likely a LiteLLM ToolCall object or similar dict
                func_details: Dict[str, Optional[str]] = {}
                # Handle LiteLLM's ToolCall object structure
                if hasattr(tc, 'function') and tc.function is not None:
                    func_details = {
                        "name": getattr(tc.function, 'name', None),
                        "arguments": getattr(tc.function, 'arguments', '{}') # arguments is a string
                    }
                elif isinstance(tc, dict) and "function" in tc and isinstance(tc["function"], dict): # Handle dict structure
                     func_details = tc["function"]

                tc_id_attr = getattr(tc, 'id', None)
                tc_id_dict = tc.get("id") if isinstance(tc, dict) else None
                tc_id = tc_id_attr if tc_id_attr is not None else tc_id_dict
                
                tc_type_attr = getattr(tc, 'type', 'function') # Default to 'function'
                tc_type_dict = tc.get("type") if isinstance(tc, dict) else None
                tc_type = tc_type_attr if tc_type_attr != 'function' else (tc_type_dict or 'function')


                serialized_tool_calls.append({
                    "id": str(tc_id) if tc_id is not None else None,
                    "type": tc_type, 
                    "function": func_details
                })
            if serialized_tool_calls:
                message_doc["tool_calls"] = serialized_tool_calls
        
        # For saving individual tool responses
        if role == "tool":
            if tool_call_id: message_doc["tool_call_id"] = str(tool_call_id)
            if name: message_doc["name"] = name # 'name' is used by OpenAI spec for tool role

        try:
            await self.history_collection.insert_one(message_doc)
            # print(f"Agent: Saved message to DB. Role: {role}, DailyID: {daily_conversation_id}")
        except Exception as e:
            print(f"Agent: Error saving message to MongoDB for daily_id '{daily_conversation_id}': {e}\n{traceback.format_exc()}")

    async def upload_file(self, file_path: str, file_name: Optional[str], file_content_type: Optional[str], client_session_id: str) -> Dict[str, Any]:
        """Asynchronously uploads a file to the MCP server using httpx."""
        try:
            if not os.path.exists(file_path):
                return {"success": False, "error": f"Agent: File not found at path: {file_path}"}

            actual_file_name = file_name or Path(file_path).name
            actual_content_type = file_content_type or "application/octet-stream"
            upload_url = f"{self.mcp_server_url}/upload"
            print(f"Agent: Uploading file '{actual_file_name}' to {upload_url}")

            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(file_path, 'rb') as f:
                    files = {'file': (actual_file_name, f, actual_content_type)}
                    response = await client.post(upload_url, files=files)
                    response.raise_for_status()
                    mcp_response_data = response.json()
            
            if mcp_response_data.get("file_path"):
                self.last_uploaded_files[client_session_id] = {
                    "path": mcp_response_data["file_path"], # Path on MCP server
                    "original_filename": actual_file_name,
                    "timestamp": datetime.now(timezone.utc)
                }
                print(f"Agent: File '{actual_file_name}' uploaded. MCP Path: {mcp_response_data['file_path']}")
            return {"success": True, "data": mcp_response_data}
        except Exception as e:
            print(f"Agent: Error in upload_file: {e}\n{traceback.format_exc()}")
            return {"success": False, "error": f"Agent error during file upload: {str(e)}"}
    def clear_last_uploaded_file_context(self, client_session_id: str) -> bool:
        if client_session_id in self.last_uploaded_files:
            removed_file_info = self.last_uploaded_files.pop(client_session_id)
            print(f"Agent: Cleared last uploaded file context for client '{client_session_id}'. Was: {removed_file_info.get('original_filename')}")
            return True
        print(f"Agent: No file context to clear for client '{client_session_id}'.")
        return False
    # --- END OF METHOD ---

    async def delete_file_on_mcp_server(self, mcp_file_path: str) -> bool:
        if not self.mcp_server_url or not mcp_file_path:
            print("Agent: MCP server URL or file path missing for deletion on MCP server.")
            return False
        delete_url = f"{self.mcp_server_url}/delete_file"
        try:
            async with httpx.AsyncClient() as client: # Make sure httpx is imported
                print(f"Agent: Requesting MCP server to delete: {mcp_file_path} via URL: {delete_url}")
                response = await client.post(delete_url, json={"file_path_on_mcp": mcp_file_path})
                response.raise_for_status() 
                print(f"Agent: Request to delete '{mcp_file_path}' on MCP server successful. Status: {response.status_code}")
                return True
        except httpx.HTTPStatusError as e:
            print(f"Agent: HTTPStatusError requesting deletion of '{mcp_file_path}' on MCP server: {e}. Response: {e.response.text if e.response else 'No response text'}")
            return False
        except Exception as e:
            # Make sure traceback is imported if you use it here
            print(f"Agent: General error requesting deletion of '{mcp_file_path}' on MCP server: {e}\n{traceback.format_exc() if 'traceback' in globals() else str(e)}")
            return False
          

    async def execute_tool_streaming(self, tool_name: str, parameters: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        """Streams results from a tool execution endpoint on the MCP server using aiohttp for SSE."""
        url = f"{self.mcp_server_url}/execute_stream/{tool_name}"
        print(f"Agent: Executing tool '{tool_name}' via streaming from {url} with params: {parameters}")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session: # 3 min timeout
                # MCP server expects JSON for POST, and Accept header for SSE
                headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream'}
                async with session.post(url, json=parameters, headers=headers) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        print(f"Agent: Tool '{tool_name}' HTTP Error {response.status}: {error_text}")
                        yield {"type": "error", "content": f"Tool '{tool_name}' execution failed with HTTP {response.status}: {error_text[:500]}"}
                        return
                    
                    # Process SSE stream
                    async for line_bytes in response.content:
                        line = line_bytes.decode('utf-8', errors='replace').strip()
                        if not line: continue # Skip empty lines

                        if line.startswith('data: '):
                            try:
                                event_data = json.loads(line[len('data: '):])
                                # print(f"Agent: Tool '{tool_name}' stream event: {event_data}")
                                yield event_data # Yield the parsed JSON object directly
                            except json.JSONDecodeError as jde:
                                print(f"Agent: JSONDecodeError for tool '{tool_name}' stream line: '{line}'. Error: {jde}")
                                # Optionally yield an error event for malformed JSON
                                # yield {"type": "error", "content": f"Malformed JSON from tool '{tool_name}': {line}"}
                                continue # Skip malformed data lines
                        # else:
                            # print(f"Agent: Tool '{tool_name}' stream, non-data line: {line}") # For debugging other SSE lines
        except asyncio.TimeoutError:
            print(f"Agent: Timeout executing tool '{tool_name}'.")
            yield {"type": "error", "content": f"Tool '{tool_name}' execution timed out."}
        except Exception as e:
            print(f"Agent: Unexpected error executing tool '{tool_name}': {e}\n{traceback.format_exc()}")
            yield {"type": "error", "content": f"Agent error while executing tool '{tool_name}': {str(e)}"}
            
    async def chat_streaming(self, user_message: str, resolved_daily_conv_id: str, client_session_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        print(f"AGENT_CHAT_STREAMING: START - DailyID='{resolved_daily_conv_id}', ClientSID='{client_session_id}', UserMsg='{user_message[:60]}...'")
        messages_for_llm: List[Dict[str, Any]] = []

        try:
            # 1. Load chat history from MongoDB
            if self.history_collection is not None and \
               resolved_daily_conv_id and not resolved_daily_conv_id.startswith(NEW_CHAT_PLACEHOLDER_PREFIX):
                print(f"Agent: Loading history for DailyID='{resolved_daily_conv_id}'")
                # Fetch relevant roles, sort by time, limit to prevent excessive context
                past_messages_cursor = self.history_collection.find(
                    {"daily_conversation_id": resolved_daily_conv_id, "role": {"$in": ["user", "assistant", "tool"]}}
                ).sort("timestamp", ASCENDING).limit(100) # Limit context window
                
                async for msg_doc in past_messages_cursor:
                    role = msg_doc.get("role")
                    content = msg_doc.get("content")
                    llm_msg: Dict[str, Any] = {"role": role}

                    if role == "user":
                        llm_msg["content"] = str(content) if content is not None else ""
                    elif role == "assistant":
                        llm_msg["content"] = str(content) if content is not None else None # LLM can take None content if tool_calls present
                        # Reconstruct tool_calls if they exist for assistant's previous turn
                        db_tool_calls = msg_doc.get("tool_calls")
                        if db_tool_calls and isinstance(db_tool_calls, list):
                            llm_msg["tool_calls"] = db_tool_calls # Already serialized in DB
                    elif role == "tool":
                        # Content for tool role is expected to be a string (JSON string of tool output)
                        if content is not None and not isinstance(content, str):
                            try: llm_msg["content"] = json.dumps(content)
                            except (TypeError, ValueError): llm_msg["content"] = str(content)
                        elif isinstance(content, str): llm_msg["content"] = content
                        else: llm_msg["content"] = "{}" # Default to empty JSON object string if None

                        if msg_doc.get("tool_call_id"): llm_msg["tool_call_id"] = str(msg_doc.get("tool_call_id"))
                        # 'name' attribute is also part of OpenAI spec for tool role messages
                        if msg_doc.get("name"): llm_msg["name"] = msg_doc.get("name")
                        elif msg_doc.get("tool_name"): llm_msg["name"] = msg_doc.get("tool_name") # Legacy?
                        else: print(f"Agent WARN: Tool message (ID: {msg_doc.get('_id')}) from DB missing 'name' or 'tool_name'.")
                    
                    messages_for_llm.append(llm_msg)
                print(f"Agent: Loaded {len(messages_for_llm)} messages from history for DailyID='{resolved_daily_conv_id}'.")

            # 2. Add System Prompt (if not already present or as first message)
            system_prompt_content =  """You are a precise and helpful assistant. Your primary goal is to use the provided tools to answer user questions.

**FILE HANDLING INSTRUCTIONS (CRITICAL - READ CAREFULLY):**
- The user can upload files (like CSV or Excel). The system tracks the most recently uploaded file for the current session.
- **IF A FILE HAS BEEN RECENTLY UPLOADED AND THE USER ASKS A QUESTION ABOUT "THE FILE", "THIS DATA", "THE UPLOADED DOCUMENT", OR ANY QUESTION THAT IMPLIES ANALYSIS, PLOTTING, OR GETTING INFORMATION (LIKE COLUMN COUNT, ROW COUNT, DATA SUMMARY) FROM THAT RECENTLY UPLOADED FILE, YOU MUST DO THE FOLLOWING:**
    1. **DECIDE to use the `analyze_and_plot_data` tool.** This is your primary tool for interacting with uploaded file data.
    2. When calling `analyze_and_plot_data`:
        - Set the `data_type` parameter to `"file"`.
        - **DO NOT provide or invent a `file_path`. The system will automatically use the correct path for the recently uploaded file.**
        - For questions like "how many columns/rows", or "describe the data", a `plot_type` like "histogram" or "line" can still be used as a vehicle for the tool to load the data. The tool's response message will often contain the info, or you can infer it. If a specific plot isn't requested for analysis, default to "histogram".
- **DO NOT ask the user to upload the file again if one has already been uploaded in the current session and they are asking about it.**
- **DO NOT ask for the filename of the uploaded file.**
- **DO NOT say you cannot access local files.** Assume the `analyze_and_plot_data` tool with `data_type: "file"` will handle it.

**OTHER TOOLS:**
- For current weather: Use `get_weather` tool with the location.

If the user asks a general question not related to a specific tool or a recently uploaded file, answer it directly.
Be concise and helpful.
"""

            if not messages_for_llm or messages_for_llm[0].get("role") != "system":
                messages_for_llm.insert(0, {"role": "system", "content": system_prompt_content})

            # 3. Add current user message
            user_msg_for_llm = {"role": "user", "content": user_message}
            messages_for_llm.append(user_msg_for_llm)
            await self.save_message_to_db(resolved_daily_conv_id, "user", user_message, client_session_id)
            
            print(f"Agent: Making initial LLM call for DailyID='{resolved_daily_conv_id}'. Tools available: {[t['function']['name'] for t in self.tools] if self.tools else 'None'}")
            


            initial_llm_response_obj: Optional[ModelResponse] = await acompletion(
                model=self.model,
                messages=messages_for_llm,
                tools=self.tools if self.tools else None, # Pass tools if available
                tool_choice="auto" if self.tools else None, # Let LLM decide if tools are present
                temperature=0.2 if self.tools else 0.7, # Lower temp for tool use, higher for creative
                stream=False # IMPORTANT: Must be False to get tool_calls object
            )

            if not initial_llm_response_obj or not initial_llm_response_obj.choices:
                err_msg = "LLM initial call failed or returned empty/invalid response."
                print(f"Agent ERROR: {err_msg} for DailyID='{resolved_daily_conv_id}'")
                yield {"type": "error", "content": err_msg}
                await self.save_message_to_db(resolved_daily_conv_id, "error", {"message": err_msg}, client_session_id)
                return

            assistant_response_message = initial_llm_response_obj.choices[0].message
            assistant_initial_content = assistant_response_message.content # Might be None if only calling tools
            assistant_tool_calls = getattr(assistant_response_message, 'tool_calls', None)

            # Save assistant's first response (text and/or tool call decision)
            await self.save_message_to_db(
                resolved_daily_conv_id, "assistant", assistant_initial_content,
                client_session_id, tool_calls=assistant_tool_calls
            )

            # Add assistant's turn to context for subsequent calls
            # model_dump() is good for LiteLLM's Pydantic models
            messages_for_llm.append(assistant_response_message.model_dump(exclude_none=True))

            # If assistant provided initial text before tool calls, stream it
            if assistant_initial_content and assistant_initial_content.strip():
                print(f"Agent: Streaming initial assistant content: '{assistant_initial_content[:100]}...'")
                yield {"type": "llm_token", "content": assistant_initial_content}
            
            # --- Handle Tool Calls ---
            if assistant_tool_calls:
                print(f"Agent: LLM decided to call tools: {[tc.function.name for tc in assistant_tool_calls]}")
                
                tool_outputs_for_llm: List[Dict[str, Any]] = []
                for tool_call in assistant_tool_calls:
                    function_name = tool_call.function.name
                    tool_call_id = str(tool_call.id) # Important for matching responses
                    
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                        print(f"Agent: Preparing to call tool '{function_name}' with ID '{tool_call_id}' and args: {function_args}")
                    except json.JSONDecodeError as jde:
                        err_msg = f"Invalid JSON arguments for tool '{function_name}': {tool_call.function.arguments}. Error: {jde}"
                        print(f"Agent ERROR: {err_msg}")
                        yield {"type": "error", "content": err_msg}
                        # Provide error feedback to LLM for this tool call
                        tool_error_output = {"role": "tool", "tool_call_id": tool_call_id, "name": function_name, "content": json.dumps({"success": False, "error": "Invalid JSON arguments from LLM"})}
                        tool_outputs_for_llm.append(tool_error_output)
                        await self.save_message_to_db(resolved_daily_conv_id, "tool", json.loads(tool_error_output["content"]), client_session_id, tool_call_id=tool_call_id, name=function_name)
                        continue # Skip to next tool call

                    # **File Handling Logic for 'analyze_and_plot_data'**
                    if function_name == "analyze_and_plot_data" and client_session_id in self.last_uploaded_files:
                        last_file_info = self.last_uploaded_files[client_session_id]
                        # Check if file was uploaded recently (e.g., within last 5-10 minutes)
                        if datetime.now(timezone.utc) - last_file_info['timestamp'] < timedelta(minutes=10):
                            print(f"Agent: OVERRIDE - Tool '{function_name}' called. Recent file upload detected for client '{client_session_id}'.")
                            print(f"Agent: Using uploaded file path: '{last_file_info['path']}' (Original: '{last_file_info['original_filename']}')")
                            function_args["data_type"] = "file" # Ensure data_type is 'file'
                            function_args["file_path"] = last_file_info['path'] # Provide the path on MCP server
                        else:
                            print(f"Agent: INFO - Tool '{function_name}' called, but last file upload for client '{client_session_id}' is older than 10 minutes. Not auto-injecting path.")
                   
                    # Stream tool execution results back to client AND capture final output for LLM
                    final_tool_status_from_stream: Optional[Dict[str, Any]] = None
                    async for tool_chunk in self.execute_tool_streaming(function_name, function_args):
                        yield tool_chunk # Stream to client
                        # Capture the last 'completed' or 'error' status message from the tool stream
                        if isinstance(tool_chunk, dict) and tool_chunk.get("status") in ["completed", "error"]:
                            final_tool_status_from_stream = tool_chunk
                    
                    # Determine the content to send back to the LLM for this tool call
                    tool_result_content_for_llm: Dict[str, Any]
                    if final_tool_status_from_stream and final_tool_status_from_stream.get("status") == "completed":
                        tool_result_content_for_llm = {"success": True, "data": final_tool_status_from_stream.get("data", {})}
                    elif final_tool_status_from_stream and final_tool_status_from_stream.get("status") == "error":
                        tool_result_content_for_llm = {"success": False, "error": final_tool_status_from_stream.get("error", "Tool failed without specific error message.")}
                    else: # Tool stream ended without a clear completed/error status
                        print(f"Agent WARNING: Tool '{function_name}' stream ended without a definitive 'completed' or 'error' status.")
                        tool_result_content_for_llm = {"success": False, "error": f"Tool '{function_name}' did not explicitly complete or error."}

                    # Save tool's final output to DB
                    await self.save_message_to_db(resolved_daily_conv_id, "tool", tool_result_content_for_llm, client_session_id, tool_call_id=tool_call_id, name=function_name)
                    
                    # Add tool output to messages for next LLM call
                    tool_outputs_for_llm.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": function_name,
                        "content": json.dumps(tool_result_content_for_llm) # LLM expects content as JSON string
                    })
                
                messages_for_llm.extend(tool_outputs_for_llm)
                
                # --- Second LLM call (streaming) to synthesize tool results ---
                print(f"Agent: Making final LLM call to synthesize tool results for DailyID='{resolved_daily_conv_id}'.")
                # For debugging:
                # print("--- LLM Request (Final) ---")
                # for m in messages_for_llm: print(json.dumps(m))
                # print("---------------------------")

                final_response_stream = await acompletion(
                    model=self.model,
                    messages=messages_for_llm,
                    # No tools or tool_choice="none" for this final summarization step
                    tools=None, 
                    tool_choice=None,
                    temperature=0.7,
                    stream=True
                )
                
                full_final_text = ""
                async for chunk in final_response_stream:
                    text_chunk = chunk.choices[0].delta.content
                    if text_chunk:
                        yield {"type": "llm_token", "content": text_chunk}
                        full_final_text += text_chunk
                
                if full_final_text.strip():
                    await self.save_message_to_db(resolved_daily_conv_id, "assistant", full_final_text, client_session_id)
                elif not assistant_initial_content: # If no initial text AND no final text
                     yield {"type": "llm_token", "content": "(Assistant processed tools but provided no further text.)"}


            elif not assistant_initial_content: # No initial text AND no tool calls
                print(f"Agent: LLM provided no initial content and no tool calls for DailyID='{resolved_daily_conv_id}'.")
                yield {"type": "llm_token", "content": "(The assistant did not provide a textual response or use tools.)"}
            
            print(f"AGENT_CHAT_STREAMING: COMPLETED - DailyID='{resolved_daily_conv_id}'")

        except litellm.exceptions.APIConnectionError as ace:
            err_msg = f"LiteLLM API Connection Error: {ace}"
            print(f"Agent CRITICAL ERROR (chat_streaming): {err_msg}\n{traceback.format_exc()}")
            yield {"type": "error", "content": f"Connection error with the language model service: {str(ace)}"}
            await self.save_message_to_db(resolved_daily_conv_id, "error", {"message": err_msg, "detail": str(ace)}, client_session_id)
        except httpx.HTTPStatusError as hse:
            err_msg = f"HTTP Error during agent operation: {hse.request.url} - {hse.response.status_code}"
            print(f"Agent CRITICAL ERROR (chat_streaming): {err_msg}\n{traceback.format_exc()}")
            yield {"type": "error", "content": f"A server error occurred: {str(hse)}"}
            await self.save_message_to_db(resolved_daily_conv_id, "error", {"message": err_msg, "detail": str(hse)}, client_session_id)
        except Exception as e:
            err_msg = f"Unexpected error in chat_streaming: {e}"
            print(f"Agent CRITICAL ERROR (chat_streaming): {err_msg}\n{traceback.format_exc()}")
            yield {"type": "error", "content": f"An unexpected agent error occurred: {str(e)}"}
            # Save the error to DB for diagnostics
            await self.save_message_to_db(resolved_daily_conv_id, "error", {"message": err_msg, "detail": str(e), "traceback": traceback.format_exc()[:2000]}, client_session_id)

# Example usage (for testing, not run when imported)
if __name__ == "__main__":
    print("This script defines the MCPAgentSSE class. For testing, you'd instantiate and call its methods.")
    # Example:
    # async def main_test():
    #     agent = MCPAgentSSE(mcp_server_url="http://localhost:8000", model="gpt-3.5-turbo", mongo_uri="mongodb://localhost:27017/")
    #     await agent.initialize_async_components()
    #     # ... more test calls
    # if os.name == 'nt': # For Windows compatibility with asyncio if needed
    #    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # asyncio.run(main_test())
