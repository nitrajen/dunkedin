"""
Stage 2: Generate AnswerPlan from FormSchema + CandidateProfile + ExperienceInfo.

Takes the extracted form schema and candidate context to produce a precise
action plan for each field, telling the CUA exactly what to do.
"""

import json

from gemini_playwright.gemini_client import GeminiClient
from gemini_playwright.models import FormSchema, AnswerPlan


def build_stage2_prompt(
    form_schema: FormSchema,
    candidate_profile: dict,
    experience_info: str,
) -> str:
    """
    Build the Stage 2 prompt following Gemini best practices.

    Uses XML-style tags for clear structure, explicit constraints,
    field mapping rules, and few-shot examples.
    """
    form_schema_json = json.dumps(form_schema.model_dump(), indent=2)
    candidate_profile_json = json.dumps(candidate_profile, indent=2)

    return f"""<role>
You are a job application assistant. Your task is to plan exactly how to fill
each form field on behalf of a candidate. You produce precise, actionable
instructions that a Computer Use Agent (CUA) will execute verbatim.
</role>

<context>
<candidate_profile>
{candidate_profile_json}
</candidate_profile>

<experience_info>
{experience_info}
</experience_info>

<form_schema>
{form_schema_json}
</form_schema>
</context>

<task>
For each field in form_schema.fields, produce a PlannedAnswer with:
- field_id: Copy from form_schema
- label: Copy from form_schema (the visible label text CUA will use to locate the field)
- field_type: Copy from form_schema
- required: Copy from form_schema
- action: One of: fill_text, fill_textarea, select_pure_choice, select_typeahead_choice, check_checkbox, select_multi_choice, skip
- proposed_text: Exact string to type (for text/textarea/typeahead/date fields; empty string if not applicable)
- target_option: Exact option to select (for pure_choice; "checked"/"unchecked" for checkbox; empty if not applicable)
- target_options: List of options to select (for multi_select only; empty list if not applicable)
- confidence: 0.0-1.0 based on how certain the match is
- reason: Brief explanation for debugging (1 sentence)
</task>

<constraints>
1. REQUIRED FIELDS: Always attempt to fill. Never skip unless truly impossible.
2. OPTIONAL FIELDS: Fill only if candidate_profile or experience_info has clear, relevant data. Otherwise action="skip".
3. FILE FIELDS: Always action="skip" (handled manually). Set reason="File upload handled manually".
4. OTHER FIELD TYPE: Always action="skip". Set reason="Unknown field type, skipped".

5. MATCHING RULES FOR CHOICE FIELDS:
   - For pure_choice: target_option MUST exactly match one of possible_values. Pick the closest semantic match.
   - For checkbox: target_option is "checked" or "unchecked" based on candidate data.
   - For multi_select: target_options is a list of exact matches from possible_values.
   - For typeahead_choice: proposed_text is what to type, target_option is the expected dropdown result.

6. TEXT FIELD RULES:
   - For text: proposed_text is the exact value to enter.
   - For textarea: proposed_text can be longer. Use experience_info to craft relevant responses for open-ended questions.
   - For date: proposed_text should be in a standard format (e.g., "MM/DD/YYYY" or "YYYY-MM-DD").

7. BE PRECISE: The CUA will use these values verbatim. Typos or wrong option names = failures.
</constraints>

<field_mapping_guide>
Use this guide to map form fields to candidate data:

| Field Pattern | Source |
|---------------|--------|
| first_name, first name | candidate_profile.personal_info.first_name |
| last_name, last name | candidate_profile.personal_info.last_name |
| full_name, legal name | candidate_profile.personal_info.full_name |
| preferred name | candidate_profile.personal_info.preferred_name |
| email | candidate_profile.personal_info.email |
| phone, telephone | candidate_profile.personal_info.phone |
| city | candidate_profile.personal_info.city |
| state | candidate_profile.personal_info.state_province |
| country | candidate_profile.personal_info.country |
| postal, zip | candidate_profile.personal_info.postal_code |
| location (freeform) | candidate_profile.personal_info.current_location_freeform |
| linkedin | candidate_profile.online_profiles.linkedin |
| github | candidate_profile.online_profiles.github |
| portfolio, website | candidate_profile.online_profiles.portfolio_site |
| gender | candidate_profile.eeo.gender → map to closest option |
| race, ethnicity, hispanic | candidate_profile.eeo.race_ethnicity → map to closest option |
| veteran | candidate_profile.eeo.veteran_status → map to closest option like "I am not a veteran" |
| disability | candidate_profile.eeo.disability_status → map to closest option like "I do not have a disability" |
| authorized to work, legally authorized | candidate_profile.work_authorization.legally_authorized → "Yes" if true |
| sponsorship, visa sponsorship, require sponsorship | candidate_profile.work_authorization.requires_sponsorship_now_or_future → "Yes" if true |
| start date, earliest start, when can you start | candidate_profile.preferences.earliest_start_date |
| relocate, willing to relocate | candidate_profile.preferences.willing_to_relocate → "Yes" if true |
| work mode, remote, hybrid, onsite | candidate_profile.preferences.work_mode |
| about yourself, tell us about, summary | Use candidate_profile.professional_summary + experience_info |
| why this role, why interested, motivation | Synthesize from experience_info highlighting relevant skills |
| cover letter, additional info | Use candidate_profile.answer_templates.generic_cover_letter_intro or synthesize from experience_info |
</field_mapping_guide>

<examples>
Example 1 - Text field (simple mapping):
Input: {{"field_id": "first_name", "label": "First Name", "field_type": "text", "required": true, "hint": "", "possible_values": []}}
Output: {{"field_id": "first_name", "field_type": "text", "required": true, "action": "fill_text", "proposed_text": "Nithin", "target_option": "", "target_options": [], "confidence": 1.0, "reason": "Direct mapping from candidate_profile.personal_info.first_name"}}

Example 2 - Pure choice with option matching:
Input: {{"field_id": "veteran_status", "label": "Veteran Status", "field_type": "pure_choice", "required": false, "hint": "Select...", "possible_values": ["I am a veteran", "I am not a veteran", "I prefer not to answer"]}}
Candidate eeo.veteran_status: "Not a veteran"
Output: {{"field_id": "veteran_status", "field_type": "pure_choice", "required": false, "action": "select_pure_choice", "proposed_text": "", "target_option": "I am not a veteran", "target_options": [], "confidence": 0.95, "reason": "Mapped 'Not a veteran' to closest option 'I am not a veteran'"}}

Example 3 - File field (always skip):
Input: {{"field_id": "resume", "label": "Resume/CV", "field_type": "file", "required": true, "hint": "", "possible_values": []}}
Output: {{"field_id": "resume", "field_type": "file", "required": true, "action": "skip", "proposed_text": "", "target_option": "", "target_options": [], "confidence": 1.0, "reason": "File upload handled manually"}}

Example 4 - Optional field with no data (skip):
Input: {{"field_id": "cover_letter_text", "label": "Cover Letter", "field_type": "textarea", "required": false, "hint": "", "possible_values": []}}
Candidate has no cover letter prepared.
Output: {{"field_id": "cover_letter_text", "field_type": "textarea", "required": false, "action": "skip", "proposed_text": "", "target_option": "", "target_options": [], "confidence": 1.0, "reason": "Optional field, no prepared cover letter in candidate profile"}}

Example 5 - Checkbox field:
Input: {{"field_id": "agree_terms", "label": "I agree to the terms and conditions", "field_type": "checkbox", "required": true, "hint": "", "possible_values": []}}
Output: {{"field_id": "agree_terms", "field_type": "checkbox", "required": true, "action": "check_checkbox", "proposed_text": "", "target_option": "checked", "target_options": [], "confidence": 1.0, "reason": "Required agreement checkbox, must be checked to submit"}}

Example 6 - Typeahead choice:
Input: {{"field_id": "location", "label": "Preferred Location", "field_type": "typeahead_choice", "required": true, "hint": "Start typing...", "possible_values": []}}
Output: {{"field_id": "location", "field_type": "typeahead_choice", "required": true, "action": "select_typeahead_choice", "proposed_text": "Dallas, TX", "target_option": "Dallas, TX, United States", "target_options": [], "confidence": 0.9, "reason": "Using candidate's current location, expecting dropdown match"}}

Example 7 - Multi-select:
Input: {{"field_id": "work_modes", "label": "Preferred work arrangements", "field_type": "multi_select", "required": false, "hint": "", "possible_values": ["Remote", "Hybrid", "On-site"]}}
Candidate preferences.work_mode: ["On-site", "Remote", "Hybrid"]
Output: {{"field_id": "work_modes", "field_type": "multi_select", "required": false, "action": "select_multi_choice", "proposed_text": "", "target_option": "", "target_options": ["Remote", "Hybrid", "On-site"], "confidence": 0.95, "reason": "Candidate open to all work modes, selecting all matching options"}}
</examples>

<output_format>
Return a JSON object with an "answers" array containing one PlannedAnswer for each field in form_schema.fields.
Ensure every field from form_schema is represented in the output, in the same order.
</output_format>"""


def generate_answer_plan(
    form_schema: FormSchema,
    candidate_profile: dict,
    experience_info: str,
    client: GeminiClient | None = None,
) -> tuple[AnswerPlan, dict]:
    """
    Generate answer plan for form fields.

    Args:
        form_schema: The extracted form schema from Stage 1.
        candidate_profile: Parsed candidate_profile.json as dict.
        experience_info: Contents of experience_info.txt.
        client: Optional GeminiClient instance. Creates one if not provided.

    Returns:
        Tuple of (AnswerPlan, token_usage_dict)
    """
    if client is None:
        client = GeminiClient()

    prompt = build_stage2_prompt(form_schema, candidate_profile, experience_info)
    return client.generate_answer_plan(prompt)
