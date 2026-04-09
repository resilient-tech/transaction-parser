from dataclasses import dataclass
from enum import Enum


class ResponseFormat(Enum):
    """Enumeration for AI model response formats."""

    JSON = "json_object"
    TEXT = "text"


class FileContentFormat(Enum):
    """How the model accepts file attachments in chat messages."""

    FILE = "file"  # OpenAI-style: type=file with file_data
    IMAGE_URL = "image_url"  # Gemini/others: type=image_url with data URI


@dataclass
class Model:
    """Base model configuration for AI services."""

    name: str
    service_provider: str
    base_url: str
    response_format: str
    supports_temperature: bool = True
    supports_vision: bool = False
    file_content_format: FileContentFormat = FileContentFormat.IMAGE_URL

    def build_file_content(
        self,
        b64_data: str,
        filename: str = "document.pdf",
        mime_type: str = "application/pdf",
    ) -> dict:
        """Build the file content block for the chat message."""
        data_uri = f"data:{mime_type};base64,{b64_data}"

        if self.file_content_format == FileContentFormat.FILE:
            return {
                "type": "file",
                "file": {
                    "filename": filename,
                    "file_data": data_uri,
                },
            }

        return {
            "type": "image_url",
            "image_url": {
                "url": data_uri,
            },
        }


### DeepSeek Models


@dataclass
class DeepSeekChat(Model):
    """DeepSeek Chat model configuration."""

    name: str = "deepseek-chat"
    service_provider: str = "DeepSeek"
    base_url: str = "https://api.deepseek.com"
    response_format: str = ResponseFormat.JSON.value


@dataclass
class DeepSeekReasoner(Model):
    """DeepSeek Reasoner model configuration."""

    name: str = "deepseek-reasoner"
    service_provider: str = "DeepSeek"
    base_url: str = "https://api.deepseek.com"
    response_format: str = ResponseFormat.TEXT.value


### OpenAI Models


@dataclass
class OpenAIGPT4o(Model):
    """OpenAI GPT-4o model configuration."""

    name: str = "gpt-4o"
    service_provider: str = "OpenAI"
    base_url: str = "https://api.openai.com/v1"
    response_format: str = ResponseFormat.JSON.value
    supports_vision: bool = True
    file_content_format: FileContentFormat = FileContentFormat.FILE


@dataclass
class OpenAIGPT4oMini(Model):
    """OpenAI GPT-4o Mini model configuration."""

    name: str = "gpt-4o-mini"
    service_provider: str = "OpenAI"
    base_url: str = "https://api.openai.com/v1"
    response_format: str = ResponseFormat.JSON.value
    supports_vision: bool = True
    file_content_format: FileContentFormat = FileContentFormat.FILE


@dataclass
class OpenAIGPT5(Model):
    """OpenAI GPT-5 model configuration."""

    name: str = "gpt-5"
    service_provider: str = "OpenAI"
    base_url: str = "https://api.openai.com/v1"
    response_format: str = ResponseFormat.JSON.value
    supports_temperature: bool = False
    supports_vision: bool = True
    file_content_format: FileContentFormat = FileContentFormat.FILE


@dataclass
class OpenAIGPT5Mini(Model):
    """OpenAI GPT-5 Mini model configuration."""

    name: str = "gpt-5-mini"
    service_provider: str = "OpenAI"
    base_url: str = "https://api.openai.com/v1"
    response_format: str = ResponseFormat.JSON.value
    supports_temperature: bool = False
    supports_vision: bool = True
    file_content_format: FileContentFormat = FileContentFormat.FILE


### Google Gemini Models


@dataclass
class GeminiPro(Model):
    """Google Gemini Pro model configuration."""

    name: str = "gemini-2.5-pro"
    service_provider: str = "Google"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    response_format: str = ResponseFormat.JSON.value
    supports_vision: bool = True


@dataclass
class GeminiFlash(Model):
    """Google Gemini Flash model configuration."""

    name: str = "gemini-2.5-flash"
    service_provider: str = "Google"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    response_format: str = ResponseFormat.JSON.value
    supports_vision: bool = True


### Model Registry

MODELS = {
    "DeepSeek Chat": DeepSeekChat(),
    "DeepSeek Reasoner": DeepSeekReasoner(),
    "OpenAI gpt-4o": OpenAIGPT4o(),
    "OpenAI gpt-4o-mini": OpenAIGPT4oMini(),
    "OpenAI gpt-5": OpenAIGPT5(),
    "OpenAI gpt-5-mini": OpenAIGPT5Mini(),
    "Google Gemini Pro-2.5": GeminiPro(),
    "Google Gemini Flash-2.5": GeminiFlash(),
}
