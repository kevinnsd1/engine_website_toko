from abc import ABC, abstractmethod

class BaseScraper(ABC):
    @abstractmethod
    async def track(self, resi: str, courier: str = None) -> dict:
        pass

    def format_response(self, status: str, history: list, summary: dict = None) -> dict:
        return {
            "status": status,
            "history": history,
            "summary": summary or {},
            "success": True
        }

    def error_response(self, message: str) -> dict:
        return {
            "message": message,
            "success": False
        }
