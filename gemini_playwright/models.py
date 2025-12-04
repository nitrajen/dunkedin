"""
Pydantic models for structured Gemini API responses.

These models enforce JSON schema validation for:
- Stage 1: FormSchema (form field extraction)
- Stage 2: AnswerPlan (planned answers for each field)
"""

from enum import Enum
from pydantic import BaseModel, Field


# =============================================================================
# Stage 1: FormSchema models
# =============================================================================

class FieldType(str, Enum):
    """Valid form field types."""
    TEXT = "text"
    TEXTAREA = "textarea"
    PURE_CHOICE = "pure_choice"
    TYPEAHEAD_CHOICE = "typeahead_choice"
    CHECKBOX = "checkbox"
    MULTI_SELECT = "multi_select"
    DATE = "date"
    FILE = "file"
    OTHER = "other"


class FormField(BaseModel):
    """A single form field extracted from screenshots."""
    field_id: str
    label: str
    field_type: FieldType
    required: bool
    hint: str
    possible_values: list[str]


class FormSchema(BaseModel):
    """Complete form schema - output of Stage 1."""
    fields: list[FormField]


# =============================================================================
# Stage 2: AnswerPlan models
# =============================================================================

class Action(str, Enum):
    """What the CUA should do for this field."""
    FILL_TEXT = "fill_text"
    FILL_TEXTAREA = "fill_textarea"
    SELECT_PURE_CHOICE = "select_pure_choice"
    SELECT_TYPEAHEAD_CHOICE = "select_typeahead_choice"
    CHECK_CHECKBOX = "check_checkbox"
    SELECT_MULTI_CHOICE = "select_multi_choice"
    SKIP = "skip"


class PlannedAnswer(BaseModel):
    """Planned action for a single form field."""
    field_id: str
    label: str
    field_type: FieldType
    required: bool
    action: Action
    proposed_text: str = Field(
        default="",
        description="Exact text to type for text/textarea/typeahead/date fields"
    )
    target_option: str = Field(
        default="",
        description="Exact option to select for pure_choice, or 'checked'/'unchecked' for checkbox"
    )
    target_options: list[str] = Field(
        default_factory=list,
        description="List of options to select for multi_select fields"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in this answer (0.0-1.0)"
    )
    reason: str = Field(
        description="Brief explanation for debugging"
    )


class AnswerPlan(BaseModel):
    """Complete answer plan - output of Stage 2."""
    answers: list[PlannedAnswer]
