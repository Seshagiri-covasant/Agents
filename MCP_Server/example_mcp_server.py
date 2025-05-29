from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
import asyncio
import json

app = FastAPI()

# Pydantic schema for get_weather input
class WeatherInput(BaseModel):
    location: str

# Dummy weather function
def get_weather(location: str) -> str:
    # Simulate real-world result
    fake_weather_data = {
        "Paris, France": "The temperature in Paris is 22°C.",
        "Bogotá, Colombia": "The temperature in Bogotá is 18°C.",
        "New York, USA": "The temperature in New York is 25°C."
    }
    return fake_weather_data.get(location, f"Sorry, I don't have weather data for {location}.")

@app.post("/get_weather")
async def get_weather_tool(data: WeatherInput):
    result = get_weather(data.location)
    return {"result": result}

# SSE endpoint required by MCP
@app.get("/sse")
async def sse():
    async def event_stream():
        yield "event: ready\ndata: ready\n\n"
        while True:
            await asyncio.sleep(60)
    return StreamingResponse(event_stream(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
