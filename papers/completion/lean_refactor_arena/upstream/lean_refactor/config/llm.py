import contextlib
import warnings
from configparser import NoOptionError, NoSectionError
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

from lean_refactor.config.config import parsed_config


def _get_optional_int(section: str, option: str) -> int | None:
    """Get optional integer config value, returning None if not found."""
    try:
        return int(parsed_config.getint(section=section, option=option))
    except (NoOptionError, NoSectionError):
        return None


def _get_optional_str(section: str, option: str) -> str | None:
    """Get optional string config value, returning None if not found."""
    try:
        return parsed_config.get(section=section, option=option)
    except (NoOptionError, NoSectionError):
        return None


def _build_extra_body(section: str, provider: str) -> dict[str, Any]:
    """
    Build extra_body dictionary with provider-specific parameters.

    Parameters
    ----------
    section : str
        Configuration section name (e.g., "FORMALIZER_AGENT_LLM")
    provider : str
        Provider type ("ollama", "vllm", "lmstudio", or "openai")

    Returns
    -------
    dict[str, Any]
        Dictionary of parameters to include in extra_body
    """
    # OpenAI doesn't support extra_body parameters
    if provider == "openai":
        return {}

    extra_body: dict[str, Any] = {}

    # num_ctx parameter (supported by all non-OpenAI providers)
    if num_ctx := _get_optional_int(section, "num_ctx"):
        extra_body["num_ctx"] = num_ctx

    # LM Studio-specific parameters
    if provider == "lmstudio" and (ttl := _get_optional_int(section, "ttl")):
        extra_body["ttl"] = ttl

    # vLLM-specific parameters (always include, Ollama will ignore them)
    if use_beam_search := _get_optional_str(section, "use_beam_search"):
        extra_body["use_beam_search"] = use_beam_search.lower() in ("true", "1", "yes")

    if best_of := _get_optional_int(section, "best_of"):
        extra_body["best_of"] = best_of

    if top_k := _get_optional_int(section, "top_k"):
        extra_body["top_k"] = top_k

    if repetition_penalty_str := _get_optional_str(section, "repetition_penalty"):
        with contextlib.suppress(ValueError):
            extra_body["repetition_penalty"] = float(repetition_penalty_str)

    if length_penalty_str := _get_optional_str(section, "length_penalty"):
        with contextlib.suppress(ValueError):
            extra_body["length_penalty"] = float(length_penalty_str)

    return extra_body


def _get_max_completion_tokens(section: str, **kwargs: Any) -> int:
    """Get max_completion_tokens from kwargs or config."""
    max_completion_tokens = kwargs.pop("max_completion_tokens", None)
    if max_completion_tokens is not None:
        return int(max_completion_tokens)

    if section == "DECOMPOSER_AGENT_LLM":
        # Try max_tokens first, then fallback to max_completion_tokens
        try:
            return parsed_config.getint(section=section, option="max_tokens")
        except (NoOptionError, NoSectionError):
            try:
                return parsed_config.getint(section=section, option="max_completion_tokens", fallback=50000)
            except (NoOptionError, NoSectionError):
                return 50000

    return parsed_config.getint(section=section, option="max_tokens", fallback=50000)


def _create_openai_llm_with_fallback(chat_openai_kwargs: dict[str, Any]) -> ChatOpenAI:
    """Create OpenAI LLM with test environment fallback."""
    import os

    openai_key = os.getenv("OPENAI_API_KEY")
    try:
        return ChatOpenAI(**chat_openai_kwargs)
    except Exception:
        # In test/CI environments without OPENAI_API_KEY, create with a dummy key
        if not openai_key or openai_key == "dummy-key-for-testing":
            warnings.warn(
                "OPENAI_API_KEY not set. OpenAI LLM functionality will not work until "
                "the API key is configured. Set the OPENAI_API_KEY environment variable.",
                UserWarning,
                stacklevel=2,
            )
            # Set a dummy key to allow module import
            os.environ["OPENAI_API_KEY"] = "dummy-key-for-testing"
            return ChatOpenAI(**chat_openai_kwargs)
        # Re-raise if it's a different error
        raise


def _create_gemini_llm(section: str, **kwargs: Any) -> ChatGoogleGenerativeAI:
    """Create a ChatGoogleGenerativeAI instance configured from config.ini.

    This is intentionally simpler than `_create_llm_safe`: it reads only a few
    fields from the given INI section and constructs a Gemini model.

    Reads from config.ini (with **kwargs overrides):
    - model
    - max_tokens (mapped to max_output_tokens)
    - max_remote_retries (mapped to max_retries)
    """

    model = kwargs.pop("model", None)
    if model is None:
        try:
            model = parsed_config.get(section=section, option="model")
        except (NoOptionError, NoSectionError) as err:
            msg = f"Model not specified in section '{section}' and not provided as argument."
            raise ValueError(msg) from err

    max_tokens = kwargs.pop("max_tokens", None)
    if max_tokens is None:
        max_tokens = _get_optional_int(section, "max_tokens")

    max_retries = kwargs.pop("max_retries", None)
    if max_retries is None:
        max_retries = parsed_config.getint(section=section, option="max_remote_retries", fallback=5)

    chat_gemini_kwargs: dict[str, Any] = {
        "model": model,
        "max_retries": int(max_retries),
    }
    if max_tokens is not None:
        chat_gemini_kwargs["max_output_tokens"] = int(max_tokens)

    chat_gemini_kwargs.update(kwargs)
    return ChatGoogleGenerativeAI(**chat_gemini_kwargs)


def _create_anthropic_llm(section: str, **kwargs: Any) -> ChatAnthropic:
    """Create a ChatAnthropic instance configured from config.ini.

    Reads from config.ini (with **kwargs overrides):
    - model
    - max_tokens
    - max_retries
    """
    model = kwargs.pop("model", None)
    if model is None:
        try:
            model = parsed_config.get(section=section, option="model")
        except (NoOptionError, NoSectionError) as err:
            msg = f"Model not specified in section '{section}' and not provided as argument."
            raise ValueError(msg) from err

    max_tokens = kwargs.pop("max_tokens", None)
    if max_tokens is None:
        max_tokens = _get_optional_int(section, "max_tokens")

    max_retries = kwargs.pop("max_retries", None)
    if max_retries is None:
        max_retries = parsed_config.getint(section=section, option="max_remote_retries", fallback=5)

    chat_anthropic_kwargs: dict[str, Any] = {
        "model": model,
        "max_retries": int(max_retries),
    }

    if max_tokens is not None:
        chat_anthropic_kwargs["max_tokens"] = int(max_tokens)

    chat_anthropic_kwargs.update(kwargs)
    return ChatAnthropic(**chat_anthropic_kwargs)


def _create_vllm_openai_llm(section: str, **kwargs: Any) -> ChatOpenAI:
    """Create a ChatOpenAI instance configured from config.ini for vLLM/OpenAI.
    
    Reads from config.ini:
    - model
    - api_key (default: "your api key goes here")
    - base_url (default: http://localhost:8000/v1)
    - max_tokens
    - temperature (default: 1)
    - reasoning_effort (optional)
    """
    model = kwargs.pop("model", None)
    if model is None:
        try:
            model = parsed_config.get(section=section, option="model")
        except (NoOptionError, NoSectionError) as err:
            msg = f"Model not specified in section '{section}' and not provided as argument."
            raise ValueError(msg) from err

    api_key = kwargs.pop("api_key", None)
    if api_key is None:
        api_key = parsed_config.get(section=section, option="api_key", fallback="your api key goes here")
        
    base_url = kwargs.pop("base_url", None)
    if base_url is None:
        # User requested to use 'url' in config but map to base_url, or 'base_url'
        base_url = parsed_config.get(section=section, option="url", fallback="http://localhost:8000/v1")

    max_tokens = kwargs.pop("max_tokens", None)
    if max_tokens is None:
        max_tokens = _get_optional_int(section, "max_tokens")

    temperature = kwargs.pop("temperature", None)
    if temperature is None:
        # Default to 1 as requested in example
        temperature = 1.0

    reasoning_effort = kwargs.pop("reasoning_effort", None)
    if reasoning_effort is None:
         reasoning_effort = _get_optional_str(section, "reasoning_effort")

    chat_openai_kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
    }
    
    if max_tokens is not None:
        chat_openai_kwargs["max_tokens"] = int(max_tokens)
        
    if reasoning_effort is not None:
        chat_openai_kwargs["reasoning_effort"] = reasoning_effort

    chat_openai_kwargs.update(kwargs)
    return ChatOpenAI(**chat_openai_kwargs)


def _create_llm_safe(section: str, **kwargs):  # type: ignore[no-untyped-def]
    """
    Create a ChatOpenAI instance configured for Ollama, vLLM, LM Studio, or OpenAI.

    Parameters
    ----------
    section : str
        Configuration section name (e.g., "FORMALIZER_AGENT_LLM")
    **kwargs
        Additional parameters to pass to ChatOpenAI (will override config values)

    Returns
    -------
    ChatOpenAI
        The ChatOpenAI instance configured for the specified provider

    Raises
    ------
    ConnectionError
        If connection to the LLM server fails
    ValueError
        If provider is invalid or required configuration is missing
    """
    # Read provider-specific configuration
    # For DECOMPOSER_AGENT_LLM, default to "openai" for backward compatibility
    default_provider = "openai" if section == "DECOMPOSER_AGENT_LLM" else "ollama"
    provider_raw = parsed_config.get(section=section, option="provider", fallback=default_provider).lower()
    provider = provider_raw.replace("-", "").replace("_", "")
    if provider not in ("ollama", "vllm", "lmstudio", "openai"):
        msg = (
            f"Invalid provider '{provider_raw}' in section '{section}'. "
            "Must be 'ollama', 'vllm', 'lmstudio', or 'openai'."
        )
        raise ValueError(msg)

    default_url_by_provider = {
        "ollama": "http://localhost:11434/v1",
        "vllm": "http://localhost:8000/v1",
        "lmstudio": "http://localhost:1234/v1",
        "openai": "https://api.openai.com/v1",
    }
    url = parsed_config.get(section=section, option="url", fallback=default_url_by_provider[provider])

    # Derive api_key from provider (ignore api_key in config for backward compatibility)
    default_api_key_by_provider = {"ollama": "ollama", "vllm": "dummy-key", "lmstudio": "lm-studio"}
    # For OpenAI, don't set api_key - let ChatOpenAI use OPENAI_API_KEY env var
    api_key = None if provider == "openai" else default_api_key_by_provider[provider]

    model = kwargs.pop("model", None)
    if model is None:
        try:
            model = parsed_config.get(section=section, option="model")
        except (NoOptionError, NoSectionError) as err:
            msg = f"Model not specified in section '{section}' and not provided as argument."
            raise ValueError(msg) from err

    max_completion_tokens = _get_max_completion_tokens(section, **kwargs)

    # Build extra_body with provider-specific parameters
    extra_body = _build_extra_body(section, provider)

    # Check if api_key or base_url are explicitly provided in kwargs (for testing/overrides)
    explicit_api_key = kwargs.pop("api_key", None)
    explicit_base_url = kwargs.pop("base_url", None)

    # Prepare ChatOpenAI arguments
    chat_openai_kwargs: dict[str, Any] = {
        "model": model,
        "max_completion_tokens": max_completion_tokens,
        "base_url": explicit_base_url if explicit_base_url is not None else url,
    }

    # Set api_key based on provider
    if provider == "openai":
        if explicit_api_key is not None:
            chat_openai_kwargs["api_key"] = explicit_api_key
    else:
        chat_openai_kwargs["api_key"] = explicit_api_key if explicit_api_key is not None else api_key

    # Add extra_body only if not empty (OpenAI doesn't support it)
    if extra_body:
        chat_openai_kwargs["extra_body"] = extra_body

    # Add any remaining kwargs (these will override the above settings)
    chat_openai_kwargs.update(kwargs)

    # Create ChatOpenAI instance with error handling for OpenAI in test environments
    if provider == "openai":
        return _create_openai_llm_with_fallback(chat_openai_kwargs)
    return ChatOpenAI(**chat_openai_kwargs)


# ============================================================================
# Planner-Based Optimizer Configuration
# ============================================================================

# Planner optimizer settings
PLANNER_MAX_CORRECTION_ATTEMPTS = parsed_config.getint(
    section="PLANNER_AGENT_LLM", option="max_correction_attempts", fallback=3
)
PLANNER_MAX_CORRECTION_ATTEMPTS_HIGH = parsed_config.getint(
    section="PLANNER_AGENT_LLM",
    option="max_correction_attempts_high",
    fallback=PLANNER_MAX_CORRECTION_ATTEMPTS,
)
PLANNER_MAX_CORRECTION_ATTEMPTS_MEDIUM = parsed_config.getint(
    section="PLANNER_AGENT_LLM",
    option="max_correction_attempts_medium",
    fallback=PLANNER_MAX_CORRECTION_ATTEMPTS,
)
PLANNER_MAX_CORRECTION_ATTEMPTS_LOW = parsed_config.getint(
    section="PLANNER_AGENT_LLM",
    option="max_correction_attempts_low",
    fallback=PLANNER_MAX_CORRECTION_ATTEMPTS,
)
PLANNER_MAX_REPLANS = parsed_config.getint(section="PLANNER_AGENT_LLM", option="max_replans", fallback=15)
PLANNER_MIN_REPLANS = parsed_config.getint(section="PLANNER_AGENT_LLM", option="min_replans", fallback=1)
PLANNER_API_BUDGET = parsed_config.getint(section="PLANNER_AGENT_LLM", option="api_budget", fallback=80)
PLANNER_MAX_RESULTS_PER_QUERY = parsed_config.getint(
    section="FINDER_AGENT_LLM", option="max_results_per_query", fallback=5
)

# Mathlib retrieval server URL
MATHLIB_RETRIEVAL_SERVER_URL = parsed_config.get(
    section="FINDER_AGENT_LLM",
    option="retrieval_server_url",
    fallback="https://bxrituxuhpc70w8w.us-east-1.aws.endpoints.huggingface.cloud",
)
