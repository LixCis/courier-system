"""
LLM Service for Order Description Standardization

This module provides AI-powered standardization of order item descriptions
using Ollama HTTP API for remote inference.
"""

import os
import threading
import time
import requests
import logging

logger = logging.getLogger(__name__)


class LLMService:
    """
    Service for standardizing order descriptions using Ollama HTTP API

    Connects to a remote Ollama instance via HTTP. Availability is cached
    for 60 seconds to avoid hammering the server with ping requests.
    """

    def __init__(self):
        """
        Initialize LLM service with Ollama configuration

        Reads from environment variables:
            OLLAMA_URL: Ollama server URL (default: http://localhost:11434)
            OLLAMA_MODEL: Model name/tag (default: qwen2.5:3b)
        """
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

        self._available = None  # Cached availability (None = not checked yet)
        self._availability_check_time = None  # When we last checked
        self._availability_cache_ttl = 60  # Cache for 60 seconds
        self._lock = threading.Lock()  # Thread safety

    def _check_available(self):
        """
        Check if Ollama is reachable and model exists (not cached)

        Returns:
            bool: True if Ollama is reachable and model is available, False otherwise
        """
        try:
            # Ping Ollama to check if it's running
            response = requests.get(
                f"{self.ollama_url}/api/tags",
                timeout=2
            )

            if response.status_code != 200:
                logger.warning(f"Ollama server returned status {response.status_code}")
                return False

            # Check if our model is in the list
            data = response.json()
            models = data.get("models", [])
            model_names = [m.get("name", "") for m in models]

            # Ollama tags bare names as ':latest' — accept both forms
            if (self.ollama_model not in model_names
                    and f"{self.ollama_model}:latest" not in model_names):
                logger.warning(f"Model {self.ollama_model} not found in Ollama. Available: {model_names}")
                return False

            return True

        except requests.exceptions.Timeout:
            logger.warning(f"Ollama timeout at {self.ollama_url}")
            return False
        except requests.exceptions.ConnectionError:
            logger.warning(f"Cannot connect to Ollama at {self.ollama_url}")
            return False
        except Exception as e:
            logger.warning(f"Error checking Ollama availability: {e}")
            return False

    def is_available(self):
        """
        Check if LLM service is available (with 60s cache)

        Returns:
            bool: True if Ollama is reachable and model exists, False otherwise
        """
        with self._lock:
            now = time.time()

            # Return cached result if still valid
            if (self._available is not None and
                self._availability_check_time is not None and
                now - self._availability_check_time < self._availability_cache_ttl):
                return self._available

            # Check availability and cache result
            self._available = self._check_available()
            self._availability_check_time = now
            return self._available

    def generate(self, prompt, **kwargs):
        """
        Thread-safe wrapper for LLM text generation via Ollama HTTP API

        Calls Ollama's /api/generate endpoint with configurable parameters.

        Args:
            prompt: Text prompt for generation
            **kwargs: Additional arguments (max_tokens, temperature, top_p, repeat_penalty, stop, echo, etc.)

        Returns:
            dict: Response dict with structure matching llama-cpp-python:
                  {'choices': [{'text': '...generated text...'}]}
                  Returns None if unavailable or error occurs.
        """
        if not self.is_available():
            return None

        with self._lock:
            try:
                # Map kwargs to Ollama API parameters
                payload = {
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                }

                # Map common inference parameters
                if "max_tokens" in kwargs:
                    payload["num_predict"] = kwargs["max_tokens"]
                if "temperature" in kwargs:
                    payload["temperature"] = kwargs["temperature"]
                if "top_p" in kwargs:
                    payload["top_p"] = kwargs["top_p"]
                if "repeat_penalty" in kwargs:
                    payload["repeat_penalty"] = kwargs["repeat_penalty"]
                if "stop" in kwargs:
                    payload["stop"] = kwargs["stop"]

                # Call Ollama API
                response = requests.post(
                    f"{self.ollama_url}/api/generate",
                    json=payload,
                    timeout=120  # Generous timeout for generation
                )

                if response.status_code != 200:
                    logger.warning(f"Ollama API error: {response.status_code}")
                    return None

                data = response.json()

                # Transform to match llama-cpp-python format
                generated_text = data.get("response", "")
                return {
                    "choices": [
                        {
                            "text": generated_text,
                        }
                    ]
                }

            except requests.exceptions.Timeout:
                logger.warning("Ollama generation timeout")
                return None
            except requests.exceptions.ConnectionError:
                logger.warning(f"Cannot connect to Ollama at {self.ollama_url}")
                return None
            except Exception as e:
                logger.warning(f"Error during Ollama generation: {e}")
                return None

    def enhance_description(self, raw_description):
        """
        Standardize and enhance order item description using AI
        Thread-safe - uses self.generate() wrapper with lock.

        Args:
            raw_description: Original description text from restaurant

        Returns:
            str: AI-enhanced description, or None if service unavailable
        """
        # Return None if no description provided
        if not raw_description or not raw_description.strip():
            return None

        # Try to check if service is available
        if not self.is_available():
            return None

        try:
            # Craft prompt with examples for better results
            prompt = f"""Úkol: Standardizuj popis jídla. Zachovej všechny informace a používej správnou češtinu.

Příklady:

Původní: Dvě pizzy margherita, jedna bez sýra, přidat bazalku
Standardizovaný: 2x pizza Margherita (1x bez sýra, přidat bazalku)

Původní: tři velký cola a hranolky velký dvakrát
Standardizovaný: 3x velká Coca-Cola, 2x velké hranolky

Původní: burger s slaninou extra sýr prosim a bez okurek
Standardizovaný: 1x burger se slaninou (extra sýr, bez okurek)

Nyní standardizuj tento popis:
{raw_description}

Standardizovaný popis:"""

            # Use thread-safe generate() method
            output = self.generate(
                prompt,
                max_tokens=256,  # Shorter max length for concise output
                temperature=0.1,  # Very low = more deterministic
                top_p=0.85,  # Slightly lower for more focused output
                repeat_penalty=1.1,  # Penalize repetition
                stop=["Původní:", "Nyní standardizuj", "\n\n"],  # Stop tokens
            )

            # Check if generation failed
            if not output:
                return None

            # Extract generated text
            enhanced = output['choices'][0]['text'].strip()

            # Basic validation
            if len(enhanced) < 5:
                logger.warning(f"AI response too short (length: {len(enhanced)})")
                return None

            # Allow reasonable expansion - short inputs can expand more
            max_allowed_length = max(
                len(raw_description) * 10,  # Allow up to 10x expansion for short inputs
                500  # But cap at 500 characters absolute maximum
            )

            if len(enhanced) > max_allowed_length:
                logger.warning(f"AI response suspiciously long")
                logger.warning(f"  Input ({len(raw_description)} chars): {raw_description[:100]}")
                logger.warning(f"  Output ({len(enhanced)} chars): {enhanced[:100]}")
                return None

            # Log successful enhancement for debugging
            logger.info(f"[AI] Enhanced: '{raw_description[:50]}...' -> '{enhanced[:50]}...' ({len(raw_description)} -> {len(enhanced)} chars)")
            return enhanced

        except Exception as e:
            logger.warning(f"Error during AI description enhancement: {e}")
            return None


# Global instance
llm_service = LLMService()


def enhance_order_description(description):
    """
    Convenience function to enhance order description

    Args:
        description: Raw description text

    Returns:
        str: Enhanced description or None if unavailable
    """
    return llm_service.enhance_description(description)
