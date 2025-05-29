from mcp.server.fastmcp import FastMCP

app = FastMCP()

@app.tool()
def get_weather(location: str) -> str:
    fake_weather_data = {
        "Paris, France": "The temperature in Paris is 22°C.",
        "Bogotá, Colombia": "The temperature in Bogotá is 18°C.",
        "New York, USA": "The temperature in New York is 25°C."
    }
    return fake_weather_data.get(location, f"Sorry, I don't have weather data for {location}.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
