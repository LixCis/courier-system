"""
LLM Service for Order Description Standardization

This module provides AI-powered standardization of order item descriptions
using a local Llama model. The model is loaded lazily to avoid slowing down
application startup.
"""

import os
from pathlib import Path


class LLMService:
    """
    Service for standardizing order descriptions using local LLM

    Uses lazy loading pattern - model is only loaded when first needed,
    not at application startup. This prevents slow startup times.
    """

    def __init__(self, model_path=None):
        """
        Initialize LLM service (does not load model yet)

        Args:
            model_path: Path to the GGUF model file. If None, uses default path.
        """
        self.llm = None
        self._model_loaded = False

        # Default model path
        if model_path is None:
            self.model_path = Path("models/llama-3.2-1b.gguf")
        else:
            self.model_path = Path(model_path)

    def _load_model(self):
        """
        Lazy load the LLM model

        Only loads once, subsequent calls do nothing.
        Returns True if model loaded successfully, False otherwise.
        """
        if self._model_loaded:
            return True

        # Check if model file exists
        if not self.model_path.exists():
            print(f"WARNING: LLM model not found at {self.model_path}")
            print(f"AI description enhancement will be disabled.")
            print(f"To enable AI features, download llama-3.2-1b.gguf and place it in models/ directory")
            return False

        try:
            from llama_cpp import Llama

            print(f"Loading LLM model from {self.model_path}...")
            self.llm = Llama(
                model_path=str(self.model_path),
                n_ctx=512,  # Context window (tokens)
                n_threads=4,  # CPU threads to use
                verbose=False  # Suppress verbose output
            )
            self._model_loaded = True
            print("LLM model loaded successfully!")
            return True

        except ImportError:
            print("ERROR: llama-cpp-python not installed!")
            print("Install it with: pip install llama-cpp-python")
            return False
        except Exception as e:
            print(f"ERROR loading LLM model: {e}")
            return False

    def is_available(self):
        """
        Check if LLM service is available

        Returns:
            bool: True if model is loaded or can be loaded, False otherwise
        """
        if self._model_loaded:
            return True
        return self._load_model()

    def enhance_description(self, raw_description):
        """
        Standardize and enhance order item description using AI

        Args:
            raw_description: Original description text from restaurant

        Returns:
            str: AI-enhanced description, or None if service unavailable
        """
        # Return None if no description provided
        if not raw_description or not raw_description.strip():
            return None

        # Try to load model if not already loaded
        if not self.is_available():
            return None

        try:
            # Craft prompt in Czech for Czech model
            prompt = f"""Úkol: Přepiš následující popis jídla do standardizovaného, profesionálního formátu.
Zachovej všechny důležité informace (názvy pokrmů, množství, příloh, poznámky).
Oprav gramatické chyby a používej konzistentní formátování.
Odpověz POUZE vylepšeným popisem, bez dalšího textu.

Původní popis:
{raw_description}

Standardizovaný popis:"""

            # Generate response
            output = self.llm(
                prompt,
                max_tokens=2048,  # Maximum length of response
                temperature=0.2,  # Lower = more focused, higher = more creative
                top_p=0.9,
                stop=["Původní popis:", "\n\n\n"],  # Stop generation at these tokens
                echo=False  # Don't include prompt in output
            )

            # Extract generated text
            enhanced = output['choices'][0]['text'].strip()

            # Basic validation - if response is too short or suspiciously long, return None
            if len(enhanced) < 5 or len(enhanced) > len(raw_description) * 3:
                print(f"WARNING: AI response looks invalid (length: {len(enhanced)})")
                return None

            return enhanced

        except Exception as e:
            print(f"ERROR during AI description enhancement: {e}")
            return None


# Global instance (lazy-loaded)
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
