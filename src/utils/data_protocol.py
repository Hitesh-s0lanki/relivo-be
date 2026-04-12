import json
from dataclasses import dataclass


@dataclass
class SSEEvent:
    data: dict | str

    def to_sse(self) -> str:
        if isinstance(self.data, str):
            return f"data: {self.data}\n\n"
        return f"data: {json.dumps(self.data)}\n\n"


class StreamProtocolBuilder:
    @staticmethod
    def message_start(message_id: str) -> SSEEvent:
        return SSEEvent({"type": "start", "messageId": message_id})

    @staticmethod
    def stream_text_start(text_id: str) -> SSEEvent:
        return SSEEvent({"type": "text-start", "id": text_id})

    @staticmethod
    def stream_text_delta(text_id: str, delta: str) -> SSEEvent:
        return SSEEvent({"type": "text-delta", "id": text_id, "delta": delta})

    @staticmethod
    def stream_text_end(text_id: str) -> SSEEvent:
        return SSEEvent({"type": "text-end", "id": text_id})

    @staticmethod
    def tool_input_start(tool_call_id: str, tool_name: str) -> SSEEvent:
        return SSEEvent({"type": "tool-input-start", "toolCallId": tool_call_id, "toolName": tool_name})

    @staticmethod
    def tool_input_available(tool_call_id: str, tool_name: str, input_obj: dict) -> SSEEvent:
        return SSEEvent({
            "type": "tool-input-available",
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "input": input_obj,
        })

    @staticmethod
    def tool_output_available(tool_call_id: str, output_obj: dict) -> SSEEvent:
        return SSEEvent({
            "type": "tool-output-available",
            "toolCallId": tool_call_id,
            "output": output_obj,
        })

    @staticmethod
    def message_end(metadata: dict) -> SSEEvent:
        return SSEEvent({"type": "finish", "messageMetadata": metadata})

    @staticmethod
    def terminate_stream() -> SSEEvent:
        return SSEEvent("[DONE]")

    @staticmethod
    def error_part(error_text: str, code: str) -> SSEEvent:
        return SSEEvent({"type": "error", "errorText": f"{code}:{error_text}"})

    @staticmethod
    def data_custom(suffix: str, data: dict) -> SSEEvent:
        return SSEEvent({"type": f"data-{suffix}", "data": data})
