from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from sse_starlette.sse import EventSourceResponse
import json
import asyncio
import requests
from typing import Dict, Any, List, Optional, AsyncGenerator
import uvicorn
from pydantic import BaseModel
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import io
import base64
import numpy as np
from pathlib import Path
import os

app = FastAPI(title="MCP Streaming Server", version="1.0.0")

class ToolRequest(BaseModel):
    tool_name: str
    parameters: Dict[str, Any]

class ToolResponse(BaseModel):
    success: bool
    data: Any = None
    error: str = None

# Create uploads directory if it doesn't exist
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Create plots directory if it doesn't exist
PLOTS_DIR = Path("plots")
PLOTS_DIR.mkdir(exist_ok=True)

# Tool implementations with streaming support
async def get_weather_streaming(location: str) -> AsyncGenerator[Dict[str, Any], None]:
    """Get current temperature for a given location with streaming updates."""
    try:
        yield {"status": "started", "message": f"Fetching weather data for {location}..."}
        await asyncio.sleep(0.5)
        
        yield {"status": "processing", "message": "Processing weather data..."}
        await asyncio.sleep(0.3)
        
        # Mock weather data
        mock_weather_data = {
            "location": location,
            "temperature": "22°C",
            "condition": "Partly Cloudy",
            "humidity": "65%",
            "wind_speed": "10 km/h"
        }
        
        yield {"status": "completed", "data": mock_weather_data, "message": "Weather data retrieved"}
        
    except Exception as e:
        yield {"status": "error", "error": str(e)}

async def get_stock_price_streaming(symbol: str) -> AsyncGenerator[Dict[str, Any], None]:
    """Get current stock price for a given symbol with streaming updates."""
    try:
        yield {"status": "started", "message": f"Fetching stock price for {symbol}..."}
        await asyncio.sleep(0.4)
        
        yield {"status": "processing", "message": "Processing market data..."}
        await asyncio.sleep(0.2)
        
        # Mock stock data
        mock_stock_data = {
            "symbol": symbol.upper(),
            "price": "$150.25",
            "change": "+2.5%",
            "volume": "1.2M"
        }
        
        yield {"status": "completed", "data": mock_stock_data, "message": "Stock data retrieved"}
        
    except Exception as e:
        yield {"status": "error", "error": str(e)}

async def analyze_and_plot_data_streaming(
    data_type: str = "sample", 
    plot_type: str = "line", 
    file_path: Optional[str] = None,
    columns: Optional[List[str]] = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """Analyze data and create plots with streaming progress updates."""
    try:
        yield {"status": "started", "message": "Starting data analysis..."}
        await asyncio.sleep(0.2)
        
        # Set style for plots
        plt.style.use('default')
        sns.set_palette("husl")
        
        # Generate or load data
        if data_type == "sample" or file_path is None:
            yield {"status": "processing", "message": "Generating sample data..."}
            await asyncio.sleep(0.3)
            # Generate sample data
            np.random.seed(42)
            df = pd.DataFrame({
                'x': range(100),
                'y1': np.random.randn(100).cumsum(),
                'y2': np.random.randn(100).cumsum(),
                'category': np.random.choice(['A', 'B', 'C'], 100)
            })
            data_source = "Generated sample data"
        else:
            yield {"status": "processing", "message": f"Loading data from {file_path}..."}
            await asyncio.sleep(0.3)
            
            # Load data from file
            if not os.path.exists(file_path):
                yield {"status": "error", "error": f"File not found: {file_path}"}
                return
            
            try:
                if file_path.endswith('.csv'):
                    df = pd.read_csv(file_path)
                elif file_path.endswith(('.xlsx', '.xls')):
                    df = pd.read_excel(file_path)
                else:
                    yield {"status": "error", "error": "Unsupported file format. Use CSV or Excel files."}
                    return
                data_source = f"Loaded from {file_path}"
            except Exception as e:
                yield {"status": "error", "error": f"Error reading file: {str(e)}"}
                return

        yield {"status": "processing", "message": "Analyzing data structure..."}
        await asyncio.sleep(0.2)
        
        # Data analysis
        analysis = {
            "shape": df.shape,
            "columns": list(df.columns),
            "data_types": df.dtypes.astype(str).to_dict(),
            "missing_values": df.isnull().sum().to_dict(),
            "numeric_summary": {}
        }
        
        # Get numeric columns for summary statistics
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 0:
            analysis["numeric_summary"] = df[numeric_cols].describe().to_dict()

        yield {"status": "processing", "message": f"Creating {plot_type} plot..."}
        await asyncio.sleep(0.4)
        
        # Create plot with smaller size and lower DPI to reduce file size
        fig, ax = plt.subplots(figsize=(10, 6))  # Reduced from (12, 8)
        
        if plot_type == "line":
            if 'date' in df.columns and len(numeric_cols) > 0:
                for col in numeric_cols[:3]:
                    ax.plot(df['date'] if 'date' in df.columns else range(len(df)), 
                           df[col], label=col, marker='o', markersize=3)  # Reduced marker size
                ax.set_xlabel('Date' if 'date' in df.columns else 'Index')
                ax.set_ylabel('Values')
                ax.legend()
                ax.set_title('Time Series Analysis')
            else:
                if len(numeric_cols) > 0:
                    ax.plot(df[numeric_cols[0]], marker='o', markersize=3)
                    ax.set_title(f'Line Plot: {numeric_cols[0]}')
                    ax.set_xlabel('Index')
                    ax.set_ylabel(numeric_cols[0])
        
        elif plot_type == "bar":
            if len(numeric_cols) >= 1:
                y_col = numeric_cols[0]
                df_sample = df.head(20)
                ax.bar(range(len(df_sample)), df_sample[y_col])
                ax.set_xlabel('Index (first 20 records)')
                ax.set_ylabel(y_col)
                ax.set_title(f'Bar Plot: {y_col}')
            else:
                yield {"status": "error", "error": "Need at least 1 numeric column for bar plot"}
                return
        
        elif plot_type == "scatter":
            if len(numeric_cols) >= 2:
                x_col, y_col = numeric_cols[0], numeric_cols[1]
                ax.scatter(df[x_col], df[y_col], alpha=0.6, s=20)  # Reduced marker size
                ax.set_xlabel(x_col)
                ax.set_ylabel(y_col)
                ax.set_title(f'Scatter Plot: {x_col} vs {y_col}')
            else:
                yield {"status": "error", "error": "Need at least 2 numeric columns for scatter plot"}
                return
        
        elif plot_type == "histogram":
            if len(numeric_cols) > 0:
                ax.hist(df[numeric_cols[0]], bins=30, alpha=0.7, edgecolor='black')
                ax.set_xlabel(numeric_cols[0])
                ax.set_ylabel('Frequency')
                ax.set_title(f'Histogram: {numeric_cols[0]}')
            else:
                yield {"status": "error", "error": "Need at least 1 numeric column for histogram"}
                return
        
        elif plot_type == "correlation":
            if len(numeric_cols) >= 2:
                corr_matrix = df[numeric_cols].corr()
                sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', center=0, ax=ax)
                ax.set_title('Correlation Matrix')
            else:
                yield {"status": "error", "error": "Need at least 2 numeric columns for correlation plot"}
                return
        
        plt.tight_layout()
        
        yield {"status": "processing", "message": "Rendering plot..."}
        await asyncio.sleep(0.3)
        
        # Save plot to file and return file path instead of base64
        plot_filename = f"plot_{plot_type}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.png"
        plot_file_path = PLOTS_DIR / plot_filename
        
        # Save with optimized settings
        plt.savefig(plot_file_path, format='png', dpi=150, bbox_inches='tight', 
                   facecolor='white', edgecolor='none')
        plt.close()
        
        # Generate a small thumbnail as base64 for preview (optional)
        fig_thumb, ax_thumb = plt.subplots(figsize=(4, 3))
        
        # Recreate a simplified version of the plot for thumbnail
        if plot_type == "line" and len(numeric_cols) > 0:
            ax_thumb.plot(df[numeric_cols[0]][:min(50, len(df))], linewidth=1)
        elif plot_type == "scatter" and len(numeric_cols) >= 2:
            sample_size = min(100, len(df))
            df_sample = df.sample(sample_size)
            ax_thumb.scatter(df_sample[numeric_cols[0]], df_sample[numeric_cols[1]], 
                           alpha=0.6, s=10)
        elif plot_type == "histogram" and len(numeric_cols) > 0:
            ax_thumb.hist(df[numeric_cols[0]], bins=20, alpha=0.7)
        
        ax_thumb.set_title(f"{plot_type.title()} Preview", fontsize=10)
        plt.tight_layout()
        
        # Convert thumbnail to base64
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', dpi=72, bbox_inches='tight', 
                   facecolor='white', edgecolor='none')
        buffer.seek(0)
        thumbnail_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        result = {
            "data_source": data_source,
            "analysis": analysis,
            "plot_file_path": str(plot_file_path),
            "thumbnail_base64": thumbnail_base64,
            "plot_type": plot_type,
            "message": f"Successfully created {plot_type} plot and analyzed data"
        }
        
        yield {"status": "completed", "data": result, "message": "Analysis completed"}
        
    except Exception as e:
        yield {"status": "error", "error": str(e)}

# Available tools registry
TOOLS_REGISTRY = {
    "get_weather": {
        "streaming_function": get_weather_streaming,
        "schema": {
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
    },
    "get_stock_price": {
        "streaming_function": get_stock_price_streaming,
        "schema": {
            "type": "function",
            "name": "get_stock_price",
            "description": "Get current stock price for a given symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock symbol e.g. AAPL, GOOGL"
                    }
                },
                "required": ["symbol"],
                "additionalProperties": False
            }
        }
    },
    "analyze_and_plot_data": {
        "streaming_function": analyze_and_plot_data_streaming,
        "schema": {
            "type": "function",
            "name": "analyze_and_plot_data",
            "description": "Analyze data and create various types of plots. Can work with CSV/Excel files or generate sample data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data_type": {
                        "type": "string",
                        "enum": ["sample", "file"],
                        "description": "Use 'sample' for demo data or 'file' to analyze uploaded data",
                        "default": "sample"
                    },
                    "plot_type": {
                        "type": "string",
                        "enum": ["line", "bar", "scatter", "histogram", "correlation"],
                        "description": "Type of plot to create",
                        "default": "line"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to CSV or Excel file (optional, uses sample data if not provided)"
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific columns to analyze (optional)"
                    }
                },
                "required": [],
                "additionalProperties": False
            }
        }
    }
}

@app.get("/")
async def root():
    return {"message": "MCP Streaming Server is running", "version": "1.0.0"}

@app.get("/tools")
async def list_tools():
    """Get list of available tools with their schemas."""
    tools = []
    for tool_name, tool_info in TOOLS_REGISTRY.items():
        tools.append(tool_info["schema"])
    return {"tools": tools}

@app.get("/tools/{tool_name}")
async def get_tool_schema(tool_name: str):
    """Get schema for a specific tool."""
    if tool_name not in TOOLS_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    return {"tool": TOOLS_REGISTRY[tool_name]["schema"]}

@app.post("/execute_stream/{tool_name}")
async def execute_tool_streaming_post(request: Request, tool_name: str, parameters: Dict[str, Any]):
    """Execute a tool with SSE streaming response using POST."""
    if tool_name not in TOOLS_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    
    async def event_generator():
        try:
            streaming_function = TOOLS_REGISTRY[tool_name]["streaming_function"]
            async for update in streaming_function(**parameters):
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                
                # Limit the size of each chunk
                data_str = json.dumps(update)
                if len(data_str) > 50000:  # 50KB limit per chunk
                    # If data is too large, send a reference instead
                    yield {
                        "event": "update",
                        "data": json.dumps({
                            "status": update.get("status"),
                            "message": update.get("message", "Large data chunk - check result"),
                            "data_truncated": True
                        })
                    }
                else:
                    yield {
                        "event": "update",
                        "data": data_str
                    }
                
            # Send completion event
            yield {
                "event": "complete",
                "data": json.dumps({"message": "Tool execution completed"})
            }
            
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)})
            }
    
    return EventSourceResponse(event_generator())

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file for analysis."""
    try:
        file_path = UPLOAD_DIR / file.filename
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        return {"message": "File uploaded successfully", "file_path": str(file_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")

@app.get("/uploads")
async def list_uploaded_files():
    """List all uploaded files."""
    try:
        files = []
        if UPLOAD_DIR.exists():
            for file_path in UPLOAD_DIR.iterdir():
                if file_path.is_file():
                    files.append({
                        "filename": file_path.name,
                        "path": str(file_path),
                        "size": file_path.stat().st_size
                    })
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing files: {str(e)}")

@app.get("/plots")
async def list_plots():
    """List all generated plots."""
    try:
        plots = []
        if PLOTS_DIR.exists():
            for plot_path in PLOTS_DIR.iterdir():
                if plot_path.is_file() and plot_path.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                    plots.append({
                        "filename": plot_path.name,
                        "path": str(plot_path),
                        "size": plot_path.stat().st_size
                    })
        return {"plots": plots}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing plots: {str(e)}")

@app.get("/plots/{filename}")
async def get_plot(filename: str):
    """Serve a plot image file."""
    plot_path = PLOTS_DIR / filename
    if not plot_path.exists():
        raise HTTPException(status_code=404, detail="Plot not found")
    
    from fastapi.responses import FileResponse
    return FileResponse(plot_path)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
