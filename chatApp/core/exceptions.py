"""Application exceptions mapped to safe API error responses."""


class AppError(Exception):
    error_code = "INTERNAL_ERROR"
    status_code = 500

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


class DocumentValidationError(AppError):
    error_code, status_code = "DOCUMENT_INVALID", 400


class StorageUploadError(AppError):
    error_code, status_code = "STORAGE_UPLOAD_FAILED", 502


class DocumentNotFoundError(AppError):
    error_code, status_code = "DOCUMENT_NOT_FOUND", 404


class IngestionError(AppError):
    error_code, status_code = "INGEST_FAILED", 500


class ConversationNotFoundError(AppError):
    error_code, status_code = "CONVERSATION_NOT_FOUND", 404


class ConversationAccessDeniedError(AppError):
    error_code, status_code = "ACCESS_DENIED", 403


class ChatbotUnavailableError(AppError):
    error_code, status_code = "CHATBOT_UNAVAILABLE", 503
