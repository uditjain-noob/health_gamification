"""Quick smoke-test: ask Gemini to reply with a single word."""
import config  # loads .env and sets up logging
from llm.gemini import GeminiClient

client = GeminiClient(api_key=config.GOOGLE_API_KEY, model=config.LLM_MODEL)
reply = client.complete(
    system="Reply with exactly one word.",
    user="Say hello.",
)
print("Gemini replied:", reply)
