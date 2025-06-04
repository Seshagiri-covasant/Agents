import asyncio
import json
import requests
from typing import List, Dict, Any, Optional, AsyncGenerator
from litellm import completion
import os
import base64
from pathlib import Path
import aiohttp
import sys

class MCPAgentSSE:
    def __init__(self, mcp_server_url: str, model: str = "gemini/gemini-1.5-flash"):
        self.mcp_server_url = mcp_server_url.rstrip('/')
        self.model = model
        self.tools = []
        self.load_tools()
    
    def load_tools(self):
        """Load available tools from MCP server."""
        try:
            response = requests.get(f"{self.mcp_server_url}/tools")
            if response.status_code == 200:
                data = response.json()
                self.tools = data.get("tools", [])
            else:
                print(f"Failed to load tools: {response.status_code}")
        except Exception as e:
            print(f"Error loading tools: {str(e)}")
    
    def upload_file(self, file_path: str) -> Dict[str, Any]:
        """Upload a file to the MCP server."""
        try:
            if not os.path.exists(file_path):
                return {"success": False, "error": f"File not found: {file_path}"}
            
            with open(file_path, 'rb') as f:
                files = {'file': f}
                response = requests.post(f"{self.mcp_server_url}/upload", files=files)
                
                if response.status_code == 200:
                    return {"success": True, "data": response.json()}
                else:
                    return {"success": False, "error": f"Upload failed: {response.status_code}"}
        
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def list_uploaded_files(self) -> List[Dict[str, Any]]:
        """List uploaded files on the server."""
        try:
            response = requests.get(f"{self.mcp_server_url}/uploads")
            if response.status_code == 200:
                return response.json().get("files", [])
            else:
                return []
        except Exception as e:
            return []
    
    def list_plots(self) -> List[Dict[str, Any]]:
        """List generated plots on the server."""
        try:
            response = requests.get(f"{self.mcp_server_url}/plots")
            if response.status_code == 200:
                return response.json().get("plots", [])
            else:
                return []
        except Exception as e:
            return []

    async def execute_tool_streaming(self, tool_name: str, parameters: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute a tool via MCP server with streaming response."""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.mcp_server_url}/execute_stream/{tool_name}"
                
                async with session.post(
                    url,
                    json=parameters,
                    headers={
                        'Accept': 'text/event-stream',
                        'Cache-Control': 'no-cache'
                    }
                ) as response:
                    
                    if response.status != 200:
                        yield {"status": "error", "error": f"HTTP {response.status}"}
                        return
                    
                    async for line in response.content:
                        line = line.decode('utf-8').strip()
                        
                        if line.startswith('data: '):
                            try:
                                data = json.loads(line[6:])
                                yield data
                            except json.JSONDecodeError:
                                continue
                        elif line.startswith('event: '):
                            continue
                        elif line == '':
                            continue
                            
        except Exception as e:
            yield {"status": "error", "error": str(e)}

    def convert_tools_for_litellm(self) -> List[Dict[str, Any]]:
        """Convert MCP tools format to LiteLLM function calling format."""
        return self.tools
    
    def save_thumbnail_image(self, thumbnail_base64: str, filename: str = "thumbnail.png") -> str:
        """Save base64 thumbnail image to file."""
        try:
            plots_dir = Path("plots")
            plots_dir.mkdir(exist_ok=True)
            
            image_data = base64.b64decode(thumbnail_base64)
            file_path = plots_dir / filename
            
            with open(file_path, 'wb') as f:
                f.write(image_data)
            
            return str(file_path)
        except Exception as e:
            return ""

    async def stream_llm_response(self, messages: List[Dict], tools: List = None) -> AsyncGenerator[str, None]:
        """Stream LLM response token by token."""
        try:
            # Use streaming completion
            response = completion(
                model=self.model,
                messages=messages,
                tools=tools or [],
                temperature=0.7,
                tool_choice="auto" if tools else "none",
                stream=True  # Enable streaming
            )
            
            # Stream tokens
            for chunk in response:
                if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                
                # Handle tool calls in streaming mode
                if hasattr(chunk.choices[0].delta, 'tool_calls') and chunk.choices[0].delta.tool_calls:
                    # For tool calls, we need to collect them and execute
                    # This is a bit complex in streaming mode, so we'll handle it separately
                    pass
                    
        except Exception as e:
            yield f"\n[Error: {str(e)}]"

    async def chat_streaming(self, user_message: str) -> AsyncGenerator[str, None]:
        """Main chat function with token-by-token streaming."""
        try:
            messages = [
                {
                    "role": "system",
                    "content": """You are a helpful assistant with access to multiple tools. Use the available tools when needed to answer user questions accurately. 
                    When you receive tool results, ALWAYS use the actual data from the tools in your response.
                    Available tools:
                    - get_weather: Get weather information for any location
                    - get_stock_price: Get stock prices for any symbol  
                    - analyze_and_plot_data: Analyze data and create plots.
                    
                    For data analysis:
                    - Use data_type="file" and specify file_path="uploads/filename.csv" for uploaded files
                    - Available plot types: line, bar, scatter, histogram, correlation
                    
                    Always provide comprehensive answers based on the ACTUAL tool results you receive."""
                },
                {"role": "user", "content": user_message}
            ]
            
            # First, check if we need tools (non-streaming to get tool calls)
            initial_response = completion(
                model=self.model,
                messages=messages,
                tools=self.convert_tools_for_litellm(),
                temperature=0.7,
                tool_choice="auto"
            )
            
            response_message = initial_response.choices[0].message
            
            # Check if LLM wants to call functions
            if hasattr(response_message, 'tool_calls') and response_message.tool_calls:
                
                # Add the assistant's response to messages
                messages.append({
                    "role": "assistant",
                    "content": response_message.content,
                    "tool_calls": response_message.tool_calls
                })
                
                # Execute each tool call
                for i, tool_call in enumerate(response_message.tool_calls):
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    yield f"\n Executing {function_name}...\n"
                    
                    # Execute with streaming
                    final_result = None
                    async for update in self.execute_tool_streaming(function_name, function_args):
                        status = update.get("status", "unknown")
                        message = update.get("message", "")
                        
                        if status == "processing" and message:
                            yield f"   {message}\n"
                        elif status == "completed":
                            final_result = {"success": True, "data": update.get("data")}
                            yield f"   Tool completed successfully!\n"
                        elif status == "error":
                            final_result = {"success": False, "error": update.get("error")}
                            yield f"   Tool failed: {update.get('error')}\n"
                    
                    # Handle plot results
                    if (final_result and final_result.get("success") and 
                        "data" in final_result and 
                        isinstance(final_result["data"], dict)):
                        
                        plot_data = final_result["data"]
                        
                        # If there's a plot file path, inform the user
                        if "plot_file_path" in plot_data:
                            yield f"   Plot saved to: {plot_data['plot_file_path']}\n"
                        
                        # If there's a thumbnail, save it locally
                        if "thumbnail_base64" in plot_data:
                            thumbnail_filename = f"thumbnail_{i+1}_{plot_data.get('plot_type', 'unknown')}.png"
                            saved_thumb_path = self.save_thumbnail_image(plot_data["thumbnail_base64"], thumbnail_filename)
                            
                            if saved_thumb_path:
                                yield f"  Thumbnail saved to: {saved_thumb_path}\n"
                                final_result["data"]["local_thumbnail_path"] = saved_thumb_path
                    
                    # Add tool result to messages
                    tool_result_content = json.dumps(final_result)
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result_content
                    })
                
                yield f"\n Assistant: "
                
                # Get final response from LLM with streaming
                async for token in self.stream_llm_response(messages, self.convert_tools_for_litellm()):
                    yield token
                    
            else:
                # No tools needed, stream the direct response
                yield f" Assistant: "
                async for token in self.stream_llm_response(messages, self.convert_tools_for_litellm()):
                    yield token
                
        except Exception as e:
            yield f"\n Error: {str(e)}"

    async def chat(self, user_message: str) -> str:
        """Non-streaming version for backward compatibility."""
        full_response = ""
        async for token in self.chat_streaming(user_message):
            full_response += token
        return full_response

    def show_help(self):
        """Display help information."""
        print("""
MCP Agent with Token-by-Token Streaming

Commands:
• help                    - Show this help
• upload <file_path>      - Upload a file for analysis
• list_files             - List uploaded files
• list_plots             - List generated plots
• quit/exit              - Exit

Available Tools:""")
        for tool in self.tools:
            print(f"• {tool['name']}: {tool['description']}")
        
        print("""
Examples:
• "What's the weather in New York?"
• "Get stock price for AAPL"
• "Create a line plot with sample data"
• "Analyze the uploaded CSV file and create a correlation plot"
        """)

async def main():
    """Main function with token-by-token streaming."""
    agent = MCPAgentSSE(
        mcp_server_url="http://localhost:8000",
        model="gemini/gemini-1.5-flash"
    )
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
            
            if user_input.lower() in ['quit', 'exit']:
                print(" Goodbye!")
                break
            
            if user_input.lower() == 'help':
                agent.show_help()
                continue
            
            if user_input.lower().startswith('upload '):
                file_path = user_input[7:].strip()
                result = agent.upload_file(file_path)
                if result["success"]:
                    print(f" File uploaded: uploads/{Path(file_path).name}")
                else:
                    print(f" Upload failed: {result['error']}")
                continue
            
            if user_input.lower() == 'list_files':
                files = agent.list_uploaded_files()
                if files:
                    print(" Uploaded files:")
                    for file in files:
                        print(f"  {file['filename']} ({file['size']} bytes)")
                else:
                    print(" No files uploaded")
                continue
            
            if user_input.lower() == 'list_plots':
                plots = agent.list_plots()
                if plots:
                    print(" Generated plots:")
                    for plot in plots:
                        print(f"  • {plot['filename']} ({plot['size']} bytes)")
                else:
                    print(" No plots generated")
                continue
            
            if not user_input:
                continue
            
            # Stream the response token by token
            print()  # Add newline for better formatting
            async for token in agent.chat_streaming(user_input):
                print(token, end='', flush=True)
            print("\n")  # Add newlines after response
            
        except KeyboardInterrupt:
            print("\n Goodbye!")
            break
        except Exception as e:
            print(f" Error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
