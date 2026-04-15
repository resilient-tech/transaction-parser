import re
from typing import Any

import frappe
from frappe import _
from openai import OpenAI

from transaction_parser.transaction_parser.ai_integration.models import MODELS
from transaction_parser.transaction_parser.ai_integration.prompts import (
    get_system_prompt,
    get_user_prompt,
)
from transaction_parser.transaction_parser.utils import is_enabled, to_dict
from transaction_parser.transaction_parser.utils.integration_request import (
    create_integration_request,
)


class AIParser:
    def __init__(self, model: str | None = None, settings=None):
        self.settings = settings or frappe.get_cached_doc("Transaction Parser Settings")

        is_enabled(self.settings)

        self.model = self._get_model(model)
        self.ai_response = {}
        if not self.model:
            frappe.throw(_(f"AI Model: {model} not found"))

    def _get_model(self, model_name: str | None):
        return MODELS.get(model_name) or MODELS.get(self.settings.default_ai_model)

    def parse(
        self,
        document_type: str,
        document_schema: dict,
        document_data: str,
        file_doc_name: str | None = None,
        company: str | None = None,
    ) -> dict:
        self._request_data = (
            f"Document Type: {document_type}\n\n"
            f"---\n"
            f"Schema:\n\n{frappe.as_json(document_schema)}\n\n"
            f"---\n"
            f"Parsed File:\n\n{document_data}"
        )

        messages = self._build_messages(
            document_type, document_schema, document_data, company
        )
        self.ai_response = self.send_message(
            messages=messages, file_doc_name=file_doc_name
        )
        return self.get_content(self.ai_response)

    def _build_messages(
        self,
        document_type: str,
        document_schema: dict,
        document_data: str,
        company: str | None = None,
    ) -> tuple:
        """Build the message structure for AI API call."""
        company_info = self._get_company_info(company) if company else ""
        system_prompt = get_system_prompt(document_schema)
        user_prompt = get_user_prompt(document_type, document_data, company_info)

        return (
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        )

    @staticmethod
    def _get_company_info(company: str) -> str:
        """Build a company context string with name and address if available."""
        from frappe.contacts.doctype.address.address import get_company_address
        from frappe.utils import strip_html

        info = f"Company: {company}"

        address = get_company_address(company)
        if address and address.company_address_display:
            address_text = strip_html(address.company_address_display).strip()

            if address_text:
                info += f"\nLocated at: {address_text}"

        return info

    def send_message(self, messages: tuple, file_doc_name: str | None = None) -> dict:
        """Send messages to AI API and handle the response."""
        log = self._create_log_entry(file_doc_name)

        try:
            response = self._make_api_call(messages)
            log.request_id = response.id

            response_dict = response.to_dict()
            log.output = response_dict

            processed_response = self._process_response(response_dict)
            log.output = processed_response

            return processed_response

        except Exception as e:
            log.error = str(e)
            raise e

        finally:
            create_integration_request(**log)

    def _create_log_entry(self, doc_name: str | None) -> frappe._dict:
        """Create a log entry for the API call."""
        log = frappe._dict(url=self.model.base_url)

        log.update(
            {
                "reference_doctype": "File",
                "reference_name": doc_name,
                "data": getattr(self, "_request_data", None),
            }
        )

        return log

    def _make_api_call(self, messages: tuple) -> Any:
        """Make the actual API call to the AI service."""
        with OpenAI(
            api_key=self.get_api_key(),
            base_url=self.model.base_url,
        ) as client:
            # Build the request parameters
            request_params = {
                "model": self.model.name,
                "messages": messages,
                "response_format": {"type": self.model.response_format},
                "stream": False,
            }

            # Only include temperature if the model supports it
            if self.model.supports_temperature:
                request_params["temperature"] = 0.7

            return client.chat.completions.create(**request_params)

    def _process_response(self, response: dict) -> dict:
        """Process the API response and extract content."""
        if not response:
            frappe.throw(_("No response received from AI service"))

        content = self.get_content(response)
        response["choices"][0]["message"]["content"] = content
        return response

    def get_api_key(self) -> str:
        """Get the API key for the configured model service provider."""
        for key in self.settings.api_keys:
            if key.service_provider == self.model.service_provider:
                return key.get_password("api_key")

        frappe.throw(
            _("API Key not found for model {0}").format(self.model.service_provider)
        )

    def get_content(self, response: dict) -> dict:
        """Extract content from API response."""
        content = response["choices"][0]["message"]["content"]

        if not isinstance(content, str):
            return content

        return self._parse_content(content)

    def _parse_content(self, content: str) -> dict:
        """Parse string content to extract JSON data."""
        if not content:
            frappe.throw(_("No response content received"))

        # Clean the content
        content = content.strip()

        try:
            return to_dict(content)

        except Exception:
            try:
                # Try to extract from markdown code blocks
                json_match = re.search(r"```json(.*)```", content, re.DOTALL)
                if json_match:
                    return to_dict(json_match.group(1).strip())

                # Try to fix common malformed JSON issues
                fixed_content = self._fix_malformed_json(content)
                if fixed_content != content:
                    return to_dict(fixed_content)

                raise Exception("No valid JSON found")

            except Exception as e:
                frappe.throw(_(f"Failed to parse response content: {e}"))

    def _fix_malformed_json(self, content: str) -> str:
        """Attempt to fix common malformed JSON issues."""
        # Remove leading/trailing whitespace
        content = content.strip()

        # If content has closing bracket but no opening bracket, add opening bracket
        if content.endswith("]") and not content.startswith("["):
            # Find where the first JSON object starts
            first_brace = content.find("{")
            if first_brace != -1:
                content = "[" + content

        # If content has opening bracket but no closing bracket, add closing bracket
        if content.startswith("[") and not content.endswith("]"):
            content = content + "]"

        # If content looks like JSON object(s) but missing array brackets
        if content.startswith("{") and content.endswith("}"):
            content = "[" + content + "]"

        # If content has multiple objects separated by commas but no array brackets
        if "{" in content and "}" in content and not content.startswith("["):
            if content.count("{") > 1 or "}, {" in content:
                content = "[" + content + "]"

        return content
