"""
Resilience patterns for the MCP Host application.

This module contains reusable components like retry decorators and circuit breakers
to make the application more robust against transient failures of external services.
"""
import logging
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception
from httpx import HTTPStatusError
from pybreaker import CircuitBreaker

logger = logging.getLogger(__name__)

# --- Retry Strategy ---

def is_server_error(exception: BaseException) -> bool:
    """
    Determines if an exception is a server-side HTTP error (5xx) that warrants a retry.
    """
    if isinstance(exception, HTTPStatusError):
        is_5xx = exception.response.status_code >= 500
        if is_5xx:
            logger.warning(f"Retrying due to server error: {exception.response.status_code} for url: {exception.request.url}")
        return is_5xx
    return False

# Generic retry decorator for API calls.
# Stops after 3 attempts.
# Waits exponentially with jitter, starting at 1s, with a max wait of 10s between retries.
api_retry_strategy = retry(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, max=10),
    retry=retry_if_exception(is_server_error),
    reraise=True  # Re-raise the final exception after all retries are exhausted
)


# --- Circuit Breaker Strategy ---

# A dictionary to hold circuit breakers for various services.
# This allows us to have a unique breaker for each external tool/service.
_breakers: dict[str, CircuitBreaker] = {}

def get_breaker(name: str, fail_max: int = 3, reset_timeout: int = 300) -> CircuitBreaker:
    """
    Gets a named circuit breaker, creating it if it doesn't exist.
    
    Args:
        name: The unique name for the service (e.g., "calendar_server", "llm_api").
        fail_max: Number of failures before opening the circuit.
        reset_timeout: Seconds before moving from 'open' to 'half-open' state.
    """
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(fail_max=fail_max, reset_timeout=reset_timeout)
        logger.info(f"Created new circuit breaker for '{name}'")
    return _breakers[name]
