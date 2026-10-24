from .base import LLMError, LLMProvider, LLMResult  # noqa: F401


def get_llm(settings, purpose: str = "translate") -> LLMProvider:
    """purpose: 'translate' or 'understand' (pass 1 may use a cheaper Gemini model)."""
    p = settings.llm_provider
    if p == "gemini":
        from .gemini import GeminiProvider
        if purpose == "understand":   # pass 1, word lookups, practice questions: cheaper model, little thinking
            return GeminiProvider(settings, model=settings.gemini_understand_model,
                                  thinking=settings.gemini_light_thinking, fallback_model=settings.gemini_model)
        return GeminiProvider(settings, model=settings.gemini_model)
    if p == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider(settings)
    if p == "mock":
        from .mock import MockProvider
        return MockProvider(settings)
    raise ValueError(f"Unknown LLM_PROVIDER '{p}'. Use gemini, ollama or mock.")
