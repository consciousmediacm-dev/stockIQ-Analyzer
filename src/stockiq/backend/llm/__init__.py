"""LLM integration package — provider wrappers, output validation, caching and track record.

To add a new provider:
  1. Add its metadata to PROVIDERS in providers.py
  2. Add a _complete_<name>(system, user, api_key) -> str function in providers.py
  3. Register it in _CALLERS
Output is parsed/validated by llm.validation (one automatic retry on bad output)
and every fresh forecast is logged for scoring by llm.track_record.
"""

from stockiq.backend.llm.providers import PROVIDERS, fetch_ai_prediction, get_secret

__all__ = ["PROVIDERS", "fetch_ai_prediction", "get_secret"]
