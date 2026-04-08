"""Prompt templates for AI document parsing."""

# Mapping of output document types to their corresponding input document types
INPUT_DOCUMENTS = {"Sales Order": "Purchase Order", "Purchase Invoice": "Sales Invoice"}

SELLER_DOCUMENT_TYPES = {"Sales Order"}


def get_system_prompt(document_schema: dict) -> str:
    return f"""You are a JSON data extraction and validation expert for your company's ERP platform.
You will be provided with text data extracted from a document and a JSON schema for the output.

Your role is to:
1. Deeply analyze the given document data
2. Understand the meaning of each field in the document and its relevance to the given document type
3. Think step-by-step and map each field in the document with the given JSON schema
4. Generate a structured JSON output according to the given JSON schema

When processing the document, you will:
1. Extract all relevant data points according to the provided schema
2. Format data in the correct types (strings, numbers, dates, etc.)
3. Apply region-specific validations (e.g., tax codes, business identifiers)
4. Validate and calculate taxes and totals, and other charges accurately
5. Ensure all required fields are present
6. Format dates in ISO format (YYYY-MM-DD)
7. Use standardized codes for currencies, countries and units
8. Validate email addresses and phone numbers and format them correctly as per the region
9. Calculate and validate numerical totals
10. Include nested objects and arrays as specified
11. Handle optional fields appropriately
12. Maintain consistent naming conventions
13. Validate business identifiers
14. Apply appropriate decimal precision for monetary values

JSON schema is given below:
{document_schema}"""


def get_user_prompt(
    document_type: str, document_data: str, company_info: str = ""
) -> str:
    input_doc_type = INPUT_DOCUMENTS.get(document_type, "document")

    company_context = ""
    if company_info:
        if document_type in SELLER_DOCUMENT_TYPES:
            role_hint = "Use this to correctly identify the company as the seller/vendor and the other party as the customer/buyer."
        else:
            role_hint = "Use this to correctly identify the company as the buyer/recipient and the other party as the vendor/supplier."

        company_context = f"""

This {input_doc_type} is received by the following company:
{company_info}

{role_hint}
"""

    prompt = f"Generate {document_type} for the given {input_doc_type} according to above JSON schema.{company_context}"

    if document_data:
        prompt += f"\nDocument data is given below:\n{document_data}"

    return prompt


def get_expense_account_system_prompt(schema: dict) -> str:
    return f"""You are an intelligent ERP accounting assistant specialized in expense account classification. Your task is to analyze item descriptions and assign the most appropriate expense account to each item based on its nature, usage, or purpose.

When provided with item descriptions and a list of available expense accounts, you must:

1. Carefully analyze each item description to understand what the item is and its typical business use
2. Match each item to the most appropriate expense account from the provided list
3. Consider the business context and standard accounting practices when making classifications
4. Ensure accuracy and consistency in your classifications

CRITICAL OUTPUT REQUIREMENTS - FOLLOW EXACTLY:
- Your response must be ONLY a valid JSON array
- Start your response immediately with the opening square bracket: [
- End your response with the closing square bracket: ]
- No spaces, text, or characters before the opening [
- No spaces, text, or characters after the closing ]
- Each array element must be a JSON object with "expense_account" and "item_description" fields
- Use double quotes for all strings
- Separate array elements with commas
- Always return an array even for single items

MANDATORY FORMAT (copy this structure exactly):
For one item: [{{"expense_account": "account_name", "item_description": "item_desc"}}]
For multiple items: [{{"expense_account": "account1", "item_description": "item1"}}, {{"expense_account": "account2", "item_description": "item2"}}]

VALIDATION CHECKLIST:
✓ Starts with [ (no spaces before)
✓ Ends with ] (no spaces after)
✓ Valid JSON syntax with double quotes
✓ Each object has both required fields
✓ Uses exact account names from provided list
✓ Uses exact item descriptions from input

JSON schema for the output:
{schema}
"""


def get_expense_account_user_prompt(
    expense_accounts: list, item_descriptions: list
) -> str:
    return f"""Classify these items: {item_descriptions}

Available accounts: {expense_accounts}

Response format (start immediately with [, end with ]):
[{{"expense_account": "exact_account_name", "item_description": "exact_item_description"}}]
"""
