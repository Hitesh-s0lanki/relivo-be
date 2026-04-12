from src.agents.base_agent import BaseAgent
from src.app_config import settings

_SYSTEM_PROMPT = (
    "You are a helpful assistant. "
    "Respond clearly and concisely to what the user says."
)


class EchoAgent(BaseAgent):
    """Dummy agent with no tools. Used to validate the full streaming pipeline."""

    def __init__(self):
        super().__init__(
            model=settings.openai_model,
            system_prompt=_SYSTEM_PROMPT,
            tools=[],
        )
