"""
Stage 1: Extract FormSchema from job application form screenshots.

Takes multiple screenshots of a form and uses Gemini Flash-Lite to produce
a deduplicated list of form fields with their types and metadata.
"""

from PIL import Image

from gemini_playwright.gemini_client import GeminiClient
from gemini_playwright.models import FormSchema


STAGE1_PROMPT = """<task>
Extract all form fields from these job application form screenshots.
</task>

<instructions>
- Deduplicate: If the same field appears in multiple screenshots (due to scrolling overlap), include it only once.
- field_id: Generate a stable snake_case identifier derived from the label (e.g., "First Name" → "first_name").
- label: The visible label text exactly as shown.
- required: true if the field has an asterisk (*) or "required" indicator; false if unclear.
- hint: Any placeholder text or helper text near the field; empty string if none.
- possible_values:
  - For pure_choice and multi_select: list the visible or inferable options.
  - For all other field types: empty array [].

Field type definitions:
- text: Single-line free text input where user can type anything.
- textarea: Multi-line free text input for longer responses.
- pure_choice: Any field where user must select EXACTLY ONE option from a fixed list of provided choices (no free text allowed).
- typeahead_choice: Any field where user types text to search/filter, then must select from the dynamically suggested results.
- checkbox: Single yes/no toggle (e.g., "I agree to terms", "Send me updates").
- multi_select: Any field where user can select ZERO OR MORE options from a fixed list (e.g., "select all that apply").
- date: Date input field or date picker.
- file: File upload field (e.g., resume, cover letter).
- other: Any field that doesn't fit the above categories.
</instructions>

<example>
A form showing:
- "First Name *" with an empty text input box
- "Resume *" with an "Upload file" button
- "Are you authorized to work in the US? *" with options "Yes" and "No" where user picks one
- "Preferred Location" with a search icon and placeholder "Start typing..."
- "Which languages do you speak?" with checkboxes for "English", "Spanish", "French"

Output:
{
  "fields": [
    {"field_id": "first_name", "label": "First Name", "field_type": "text", "required": true, "hint": "", "possible_values": []},
    {"field_id": "resume", "label": "Resume", "field_type": "file", "required": true, "hint": "", "possible_values": []},
    {"field_id": "authorized_to_work_in_us", "label": "Are you authorized to work in the US?", "field_type": "pure_choice", "required": true, "hint": "", "possible_values": ["Yes", "No"]},
    {"field_id": "preferred_location", "label": "Preferred Location", "field_type": "typeahead_choice", "required": false, "hint": "Start typing...", "possible_values": []},
    {"field_id": "languages_spoken", "label": "Which languages do you speak?", "field_type": "multi_select", "required": false, "hint": "", "possible_values": ["English", "Spanish", "French"]}
  ]
}
</example>"""


def extract_form_schema(
    screenshots: list[Image.Image],
    client: GeminiClient | None = None,
) -> tuple[FormSchema, dict]:
    """
    Extract form schema from screenshots.

    Args:
        screenshots: List of PIL Images covering the full form.
        client: Optional GeminiClient instance. Creates one if not provided.

    Returns:
        Tuple of (FormSchema, token_usage_dict)
    """
    if client is None:
        client = GeminiClient()

    return client.extract_form_schema(screenshots, STAGE1_PROMPT)
