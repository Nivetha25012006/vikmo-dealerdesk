from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.exceptions import ValidationErrorAPIError
from core.assistant.llm_client import process_chat_message


class AssistantChatView(APIView):
    def post(self, request):
        data = request.data
        if not isinstance(data, dict):
            raise ValidationErrorAPIError("Request body must be a JSON object.")

        session_id = data.get("session_id")
        dealer_id = data.get("dealer_id")
        message = data.get("message")

        if not session_id or not isinstance(session_id, str):
            raise ValidationErrorAPIError("'session_id' is required and must be a string.")

        if dealer_id is None or not isinstance(dealer_id, int):
            raise ValidationErrorAPIError("'dealer_id' is required and must be an integer.")

        if not message or not isinstance(message, str):
            raise ValidationErrorAPIError("'message' is required and must be a non-empty string.")

        result = process_chat_message(
            session_id=session_id.strip(),
            dealer_id=dealer_id,
            message=message.strip(),
        )

        return Response(result, status=status.HTTP_200_OK)
