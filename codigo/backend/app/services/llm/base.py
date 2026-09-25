from abc import ABC, abstractmethod


class LLMClient(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...
