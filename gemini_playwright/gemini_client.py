"""
Gemini API client for form field extraction, answer planning, and computer use.

Uses google-genai SDK with structured output via Pydantic models.
"""

from PIL import Image

from google import genai
from google.genai import types

from gemini_playwright.config import GEMINI_API_KEY, MODEL_FLASH_LITE, MODEL_COMPUTER_USE
from gemini_playwright.models import FormSchema, AnswerPlan


class GeminiClient:
    """Client for Gemini API calls with structured output."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("Gemini API key not provided. Set gemini_api_key env var.")
        self.client = genai.Client(api_key=self.api_key)

    def extract_form_schema(
        self, screenshots: list[Image.Image], prompt: str
    ) -> tuple[FormSchema, dict]:
        """
        Extract form schema from screenshots using Flash-Lite.

        Args:
            screenshots: List of PIL Images of the form.
            prompt: The extraction prompt.

        Returns:
            Tuple of (FormSchema, token_usage_dict)
        """
        # Build contents: images first, then prompt text
        contents = list(screenshots) + [prompt]

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=FormSchema,
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        )

        response = self.client.models.generate_content(
            model=MODEL_FLASH_LITE,
            contents=contents,
            config=config,
        )

        # Extract token usage
        usage = {
            "prompt_tokens": response.usage_metadata.prompt_token_count,
            "response_tokens": response.usage_metadata.candidates_token_count,
            "total_tokens": response.usage_metadata.total_token_count,
        }

        # Get parsed Pydantic object directly
        form_schema: FormSchema = response.parsed

        return form_schema, usage

    def generate_answer_plan(self, prompt: str) -> tuple[AnswerPlan, dict]:
        """
        Generate answer plan for form fields using Flash-Lite.

        Args:
            prompt: The answer planning prompt (includes candidate profile,
                    experience info, and form schema).

        Returns:
            Tuple of (AnswerPlan, token_usage_dict)
        """
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AnswerPlan,
        )

        response = self.client.models.generate_content(
            model=MODEL_FLASH_LITE,
            contents=prompt,
            config=config,
        )

        # Extract token usage
        usage = {
            "prompt_tokens": response.usage_metadata.prompt_token_count,
            "response_tokens": response.usage_metadata.candidates_token_count,
            "total_tokens": response.usage_metadata.total_token_count,
        }

        # Get parsed Pydantic object directly
        answer_plan: AnswerPlan = response.parsed

        return answer_plan, usage

    def execute_computer_use(
        self, screenshot_bytes: bytes, prompt: str
    ) -> tuple[list, dict]:
        """
        Execute computer use action with screenshot and prompt.

        Args:
            screenshot_bytes: PNG screenshot as bytes.
            prompt: The instruction prompt for CUA.

        Returns:
            Tuple of (list of function_calls, token_usage_dict)
        """
        config = types.GenerateContentConfig(
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                    )
                )
            ],
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        )

        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part(text=prompt),
                    types.Part.from_bytes(data=screenshot_bytes, mime_type="image/png"),
                ],
            )
        ]

        response = self.client.models.generate_content(
            model=MODEL_COMPUTER_USE,
            contents=contents,
            config=config,
        )

        # Extract token usage (use short keys for consistency with CUA usage)
        usage = {
            "prompt": response.usage_metadata.prompt_token_count,
            "response": response.usage_metadata.candidates_token_count,
            "total": response.usage_metadata.total_token_count,
        }

        # Extract function calls from response
        function_calls = []
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    function_calls.append(part.function_call)

        return function_calls, usage
