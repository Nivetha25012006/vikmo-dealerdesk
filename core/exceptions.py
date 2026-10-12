from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.http import Http404


class DealerDeskAPIError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, code="VALIDATION_ERROR", message="Validation error", details=None, status_code=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details if details is not None else []
        if status_code:
            self.status_code = status_code


class ValidationErrorAPIError(DealerDeskAPIError):
    def __init__(self, message="Validation error", details=None):
        super().__init__(code="VALIDATION_ERROR", message=message, details=details, status_code=status.HTTP_400_BAD_REQUEST)


class NotFoundAPIError(DealerDeskAPIError):
    def __init__(self, message="Resource not found", details=None):
        super().__init__(code="NOT_FOUND", message=message, details=details, status_code=status.HTTP_404_NOT_FOUND)


class DuplicateAPIError(DealerDeskAPIError):
    def __init__(self, message="Duplicate resource", details=None):
        super().__init__(code="DUPLICATE", message=message, details=details, status_code=status.HTTP_409_CONFLICT)


class InsufficientStockAPIError(DealerDeskAPIError):
    def __init__(self, message="Insufficient stock", details=None):
        super().__init__(code="INSUFFICIENT_STOCK", message=message, details=details, status_code=status.HTTP_409_CONFLICT)


class InvalidTransitionAPIError(DealerDeskAPIError):
    def __init__(self, message="Invalid transition", details=None):
        super().__init__(code="INVALID_TRANSITION", message=message, details=details, status_code=status.HTTP_409_CONFLICT)


class OrderLockedAPIError(DealerDeskAPIError):
    def __init__(self, message="Order locked: editing is only allowed for DRAFT orders", details=None):
        super().__init__(code="ORDER_LOCKED", message=message, details=details, status_code=status.HTTP_409_CONFLICT)


class IdempotencyConflictAPIError(DealerDeskAPIError):
    def __init__(self, message="Idempotency key reused with different request body", details=None):
        super().__init__(code="IDEMPOTENCY_CONFLICT", message=message, details=details, status_code=status.HTTP_409_CONFLICT)


def custom_exception_handler(exc, context):
    """
    Standardize all exception responses to:
    {"error": {"code": "...", "message": "...", "details": [...]}}
    """
    if isinstance(exc, DealerDeskAPIError):
        return Response(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            status=exc.status_code,
        )

    if isinstance(exc, Http404):
        return Response(
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": str(exc) or "The requested resource was not found.",
                    "details": [],
                }
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    # Call REST framework's default exception handler to get the standard response.
    response = exception_handler(exc, context)

    if response is not None:
        status_code = response.status_code
        if status_code == 404:
            code = "NOT_FOUND"
        elif status_code == 409:
            code = "DUPLICATE"
        else:
            code = "VALIDATION_ERROR"

        # Format details from response.data
        details = []
        msg = "Request validation failed"
        if isinstance(response.data, dict):
            if "detail" in response.data:
                msg = str(response.data["detail"])
            else:
                for field, errs in response.data.items():
                    if isinstance(errs, list):
                        for e in errs:
                            details.append(f"{field}: {e}")
                    else:
                        details.append(f"{field}: {errs}")
                if details:
                    msg = "; ".join(details)
        elif isinstance(response.data, list):
            details = [str(x) for x in response.data]
            msg = "; ".join(details)

        response.data = {
            "error": {
                "code": code,
                "message": msg,
                "details": details,
            }
        }
        return response

    return None
