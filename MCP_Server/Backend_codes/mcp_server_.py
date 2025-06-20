# File: example_mcp_server.py 

from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse
from werkzeug.utils import secure_filename
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
import json, asyncio, os, uvicorn, io, base64
from pathlib import Path
from typing import Dict, Any, List, Optional, AsyncGenerator
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from PIL import Image
import traceback
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

load_dotenv()
app = FastAPI(title="MCP Tool Server", version="1.2.0")
WEATHERMAP_API_KEY = os.getenv("WEATHERMAP_API_KEY")

BASE_DIR = Path(__file__).resolve().parent # Gets the directory of the current script
UPLOAD_DIR = BASE_DIR / "uploads"
PLOTS_DIR = BASE_DIR / "plots" # Define PLOTS_DIR here

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

# --- CORS MIDDLEWARE ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)


async def get_weather_streaming(location: str) -> AsyncGenerator[ServerSentEvent, None]: # Change return type hint
    import requests 
    print(f"MCP_TOOL: get_weather_streaming called for location: {location}")
    if not WEATHERMAP_API_KEY:
        print("MCP_TOOL: WEATHERMAP_API_KEY not found!")
        # Yield a ServerSentEvent with the data payload
        yield ServerSentEvent(data=json.dumps({"status": "error", "error": "Weather API key not configured on the server."}))
        return
    try:
        print("MCP_TOOL: Yielding 'started' status.")
        yield ServerSentEvent(data=json.dumps({"status": "started", "message": f"Fetching weather for {location}..."}))
        
        base_url = "http://api.openweathermap.org/data/2.5/weather"
        params = {'q': location, 'appid': WEATHERMAP_API_KEY, 'units': 'metric'}
        
        print(f"MCP_TOOL: Preparing to call OpenWeatherMap API for {location}")
        def _make_call():
            # ... (your _make_call logic remains the same) ...
            try:
                print("MCP_TOOL: (Thread) Making requests.get call...")
                r = requests.get(base_url, params=params, timeout=10)
                print(f"MCP_TOOL: (Thread) OpenWeatherMap API responded with status: {r.status_code}")
                r.raise_for_status()
                return r.json()
            except requests.exceptions.HTTPError as httpe:
                print(f"MCP_TOOL: (Thread) HTTPError from OpenWeatherMap: {httpe}. Response text: {r.text if 'r' in locals() else 'N/A'}")
                return {"error": f"Weather API HTTP Error: {httpe.response.status_code} - {r.text[:100] if 'r' in locals() else str(httpe)}"}
            except Exception as e:
                print(f"MCP_TOOL: (Thread) Exception in _make_call: {e}")
                return {"error": str(e)}

        api_data = await asyncio.to_thread(_make_call)
        print(f"MCP_TOOL: OpenWeatherMap API call completed. Result: {str(api_data)[:200]}...")

        if "error" in api_data:
            print(f"MCP_TOOL: Error from API call: {api_data['error']}")
            yield ServerSentEvent(data=json.dumps({"status": "error", "error": api_data["error"]}))
            return

        if api_data.get("cod") == 200:
            main = api_data.get("main", {}); weather = api_data.get("weather", [{}])[0]
            payload_data = {"location": api_data.get("name"), "temperature": f"{main.get('temp')}°C", "condition": weather.get("description", "").capitalize()}
            print("MCP_TOOL: Yielding 'completed' status with weather data.")
            yield ServerSentEvent(data=json.dumps({"status": "completed", "data": payload_data, "message": "Weather data retrieved."}))
        else:
            error_msg = api_data.get("message", "Unknown weather API error.")
            print(f"MCP_TOOL: Weather API returned non-200 code: {api_data.get('cod')}. Message: {error_msg}")
            yield ServerSentEvent(data=json.dumps({"status": "error", "error": error_msg}))
    except Exception as e:
        print(f"MCP_TOOL: Unexpected error in get_weather_streaming: {e}\n{traceback.format_exc()}")
        yield ServerSentEvent(data=json.dumps({"status": "error", "error": f"Unexpected server error in weather tool: {str(e)}"}))
    finally:
        print(f"MCP_TOOL: get_weather_streaming for {location} is finishing.")

# Apply the same ServerSentEvent(data=json.dumps(...)) pattern to analyze_and_plot_data_streaming
# In example_mcp_server.py

# Ensure these imports are at the top of the file:
import matplotlib
matplotlib.use('Agg') # Use a non-interactive backend for Matplotlib BEFORE pyplot import
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from pathlib import Path
import io
import base64
from PIL import Image
# ... other necessary imports for this file

# ... (PLOTS_DIR, UPLOAD_DIR definitions, FastAPI app instance, etc.) ...

async def analyze_and_plot_data_streaming(data_type: str="sample", plot_type: str="line", file_path: Optional[str]=None) -> AsyncGenerator[ServerSentEvent, None]:
    def _blocking_plot_logic():
        # PLOTS_DIR should now be accessible here as a global variable from this module
        plot_target_name = "Sample Data" # Default for messages

        if data_type == "sample" or file_path is None:
            df = pd.DataFrame({'x_axis_sample': range(100), 
                               'y_axis_sample_1': np.random.randn(100).cumsum(), 
                               'y_axis_sample_2': np.random.randn(100).cumsum()})
            print(f"MCP_TOOL: Using sample data for {plot_type} plot.")
        else:
            if not file_path or not Path(file_path).is_file():
                print(f"MCP_TOOL: Error - File not found or path invalid: {file_path}")
                return {"status": "error", "error": f"File not found or path invalid: {file_path}"}
            
            plot_target_name = Path(file_path).name # Use actual filename for messages
            print(f"MCP_TOOL: Reading data from file: {file_path}")
            try:
                if str(file_path).lower().endswith('.csv'):
                    df = pd.read_csv(file_path)
                elif str(file_path).lower().endswith(('.xls', '.xlsx')):
                    df = pd.read_excel(file_path)
                else:
                    return {"status": "error", "error": f"Unsupported file type: {Path(file_path).suffix}"}
                
                if df.empty:
                     return {"status": "error", "error": f"File '{plot_target_name}' is empty."}
                if len(df.columns) < 1: # Check if there are any columns at all
                     return {"status": "error", "error": f"File '{plot_target_name}' has no columns or could not be parsed correctly."}

            except Exception as e:
                print(f"MCP_TOOL: Error reading file {file_path}: {e}")
                return {"status": "error", "error": f"Error reading file '{plot_target_name}': {str(e)}"}

        try:
            num_rows, num_cols = df.shape
            column_names = list(df.columns)
            metadata_message = f"The file '{plot_target_name}' has {num_rows} rows and {num_cols} columns. Column names are: {', '.join(column_names[:5])}{'...' if len(column_names) > 5 else ''}."
            print(f"MCP_TOOL: Metadata extracted: {metadata_message}")
            fig, ax = plt.subplots(figsize=(10, 6))
            
            # More robust column selection for plotting
            if plot_type == "line":
                if len(df.columns) >= 2:
                    x_col, y_col = df.columns[0], df.columns[1]
                    ax.plot(df[x_col], df[y_col])
                    ax.set_xlabel(x_col)
                    ax.set_ylabel(y_col)
                elif len(df.columns) == 1: # If only one column, plot it against its index
                    x_col = df.columns[0]
                    ax.plot(df[x_col])
                    ax.set_xlabel("Index")
                    ax.set_ylabel(x_col)
                else: # Should have been caught by earlier check, but as a safeguard
                    return {"status": "error", "error": f"Not enough columns in '{plot_target_name}' for a line plot."}
            
            elif plot_type == "histogram":
                if len(df.columns) >= 1: # Need at least one column for histogram
                    target_col = df.columns[0] # Use the first column
                    ax.hist(df[target_col], bins=20)
                    ax.set_xlabel(target_col)
                    ax.set_ylabel("Frequency")
                else: # Should have been caught
                    return {"status": "error", "error": f"No columns found in '{plot_target_name}' for a histogram."}
            
            elif plot_type == "scatter":
                if len(df.columns) >= 2:
                    x_col, y_col = df.columns[0], df.columns[1]
                    ax.scatter(df[x_col], df[y_col])
                    ax.set_xlabel(x_col)
                    ax.set_ylabel(y_col)
                else:
                    return {"status": "error", "error": f"Not enough columns in '{plot_target_name}' for a scatter plot (requires at least 2)."}
            else:
                 return {"status": "error", "error": f"Unsupported plot type requested: {plot_type}"}

            ax.set_title(f'{plot_type.title()} Plot of {plot_target_name}')
            plt.tight_layout()
            
            # Use a safe filename based on original filename and plot type
            base_plot_filename = Path(file_path).stem if file_path else 'sample'
            plot_filename_safe = "".join(c if c.isalnum() or c in ['_','-'] else '_' for c in base_plot_filename)
            
            plot_filename = f"plot_{plot_filename_safe}_{plot_type}_{pd.Timestamp.now().strftime('%Y%m%d%H%M%S')}.png"
            full_plot_path_on_server = PLOTS_DIR / plot_filename # PLOTS_DIR is global
            plt.savefig(full_plot_path_on_server, format='png')
            plt.close(fig) 
            print(f"MCP_TOOL: Plot saved to {full_plot_path_on_server}")
            
            img = Image.open(full_plot_path_on_server)
            img.thumbnail((200, 150)) 
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            thumbnail_base64 = base64.b64encode(buffer.getvalue()).decode()
            
            plot_result_data = {
                "plot_file_path": plot_filename, 
                "thumbnail_base64": thumbnail_base64,
                "num_rows": num_rows,
                "num_columns": num_cols,
                "column_names": column_names,
                "data_preview": df.head(3).to_dict(orient='records')
                
            }
            completion_message = f"Successfully analyzed '{plot_target_name}'. {metadata_message} A {plot_type} plot was also generated."
            return {"status": "completed", "data": plot_result_data, "message": "Analysis and plotting complete."}
        
        except Exception as plot_err:
            print(f"MCP_TOOL: Error during plotting for '{plot_target_name}': {plot_err}\n{traceback.format_exc()}")
            return {"status": "error", "error": f"Error during plotting '{plot_target_name}': {str(plot_err)}"}

    # --- This is the start of analyze_and_plot_data_streaming async generator ---
    print(f"MCP_TOOL: analyze_and_plot_data_streaming called. DataType: {data_type}, PlotType: {plot_type}, File: {file_path}")
    yield ServerSentEvent(data=json.dumps({"status": "started", "message": "Starting data analysis..."}))
    
    final_result_dict = await asyncio.to_thread(_blocking_plot_logic) 
    
    print(f"MCP_TOOL: analyze_and_plot_data_streaming final result: {str(final_result_dict)[:200]}...")
    yield ServerSentEvent(data=json.dumps(final_result_dict)) # final_result_dict already contains status
    print(f"MCP_TOOL: analyze_and_plot_data_streaming for {plot_type} is finishing.")
TOOLS_REGISTRY = {
    "get_weather": {
        "streaming_function": get_weather_streaming, # The actual async generator function
        "schema": {
            # "type": "function", # This outer "type: function" is usually added by the agent when passing to LiteLLM
            "name": "get_weather",
            "description": "Get the current weather conditions for a specified city or location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, or city and country, e.g., 'San Francisco, CA' or 'London, UK'."
                    }
                },
                "required": ["location"]
            }
        }
    },
    "analyze_and_plot_data": {
        "streaming_function": analyze_and_plot_data_streaming, # The actual async generator function
        "schema": {
            # "type": "function",
            "name": "analyze_and_plot_data",
            "description": "Analyzes data and creates a plot. Can use sample data or data from an uploaded file if the user just uploaded one and refers to it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data_type": {
                        "type": "string",
                        "description": "The source of the data. Use 'file' if the user recently uploaded a file and is asking about it. Otherwise, 'sample' can be used for demonstration.",
                        "enum": ["sample", "file"],
                        "default": "sample"
                    },
                    "plot_type": {
                        "type": "string",
                        "description": "The type of plot to generate.",
                        "enum": ["line", "histogram", "scatter"],
                        "default": "line"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Analyzes data from an uploaded file or sample data. Provides metadata (like row/column counts) and can create plots. If a file was recently uploaded and the user asks about its properties or to visualize it, use this tool with data_type='file'.",
                        # This parameter is more for internal use by the agent when injecting a path for an uploaded file.
                        # The LLM itself usually doesn't need to provide file_path directly unless explicitly told the path.
                    }
                    # You could add more parameters here like column names for plotting if your function supports it
                    # "x_column": {"type": "string", "description": "Name of the column for the x-axis."},
                    # "y_column": {"type": "string", "description": "Name of the column for the y-axis."}
                },
                "required": ["data_type", "plot_type"] # file_path is not strictly required from LLM
            }
        }
    }
    # You can add more tools here following the same pattern
    # "get_stock_price": { ... }
}

# --- API Endpoints that use the registry ---
@app.post("/upload") # Make sure this path is exactly "/upload" and method is POST
async def mcp_upload_file_endpoint(file: UploadFile = File(...)): # Parameter name 'file' matches what agent sends
    try:
        # Secure the filename provided by the client
        original_filename = file.filename
        if not original_filename: # Handle case where filename might be empty or invalid
             raise HTTPException(status_code=400, detail="Filename not provided or invalid.")
        
        # Use werkzeug.utils.secure_filename for basic santization
        # You might want more robust sanitization depending on your security needs
        filename = secure_filename(original_filename)
        if not filename: # If secure_filename strips everything (e.g., "../../../../etc/passwd")
            filename = f"unsafe_filename_{Path(original_filename).suffix}" # Or generate a UUID based name

        file_path_on_mcp_server = UPLOAD_DIR / filename
        
        # Save the file content
        with open(file_path_on_mcp_server, "wb") as f:
            content = await file.read() # Read file content
            f.write(content)
        
        print(f"MCP_SERVER: File '{filename}' (from '{original_filename}') uploaded successfully to '{file_path_on_mcp_server}'.")
        # The agent expects a JSON response with "file_path"
        return {
            "message": "File uploaded successfully to MCP server.",
            "file_path": str(file_path_on_mcp_server), # Path on the MCP server itself
            "original_filename": original_filename,
            "mcp_filename": filename # The potentially secured filename used on MCP server
        }
    except HTTPException:
        raise # Re-raise FastAPI's HTTPExceptions
    except Exception as e:
        print(f"MCP_SERVER: Error during file upload at /upload: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error during file upload: {str(e)}")
    finally:
        if file:
            await file.close()

class FileDeleteRequest(BaseModel):
    file_path_on_mcp: str

@app.post("/delete_file")
async def mcp_delete_file_endpoint(payload: FileDeleteRequest):
    file_to_delete_str = payload.file_path_on_mcp
    
    # Basic security: ensure path is within UPLOAD_DIR or PLOTS_DIR
    # This is a very basic check; production systems need more robust path validation.
    # Convert to absolute path to resolve any '..'
    try:
        abs_file_to_delete = Path(file_to_delete_str).resolve()
        is_in_uploads = abs_file_to_delete.is_relative_to(UPLOAD_DIR.resolve())
        is_in_plots = abs_file_to_delete.is_relative_to(PLOTS_DIR.resolve())

        if not (is_in_uploads or is_in_plots):
            print(f"MCP_SERVER: Attempt to delete file outside designated dirs: {file_to_delete_str}")
            raise HTTPException(status_code=403, detail="Deletion of this file path is not allowed.")

        if abs_file_to_delete.exists() and abs_file_to_delete.is_file():
            os.remove(abs_file_to_delete)
            print(f"MCP_SERVER: Deleted file: {abs_file_to_delete}")
            return {"message": f"File '{abs_file_to_delete.name}' deleted successfully from MCP server."}
        else:
            print(f"MCP_SERVER: File not found for deletion or is not a file: {abs_file_to_delete}")
            raise HTTPException(status_code=404, detail=f"File not found on MCP server or is not a file: {file_to_delete_str}")
    except HTTPException:
        raise
    except Exception as e:
        print(f"MCP_SERVER: Error deleting file {file_to_delete_str}: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting file on MCP server: {str(e)}")

@app.get("/tools")
async def list_tools_endpoint():
    """Returns the JSON schemas of all registered tools."""
    # The agent expects a list of schemas directly
    return {"tools": [info["schema"] for info in TOOLS_REGISTRY.values()]}

@app.post("/execute_stream/{tool_name}")
async def execute_tool_endpoint(request: Request, tool_name: str):
    """Executes a registered tool by its name with the provided parameters."""
    if tool_name not in TOOLS_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found in registry.")
    
    try:
        params = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload for tool parameters.")

    tool_info = TOOLS_REGISTRY[tool_name]
    streaming_func = tool_info["streaming_function"]
    
    print(f"MCP_SERVER: Executing tool '{tool_name}' with params: {params}")
    # EventSourceResponse expects an async generator that yields strings or ServerSentEvent objects
    return EventSourceResponse(streaming_func(**params))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
