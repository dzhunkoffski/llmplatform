import itertools
from app.core.config import settings

class RoundRobinBalancer:
    def __init__(self, providers: list[str]):
        self.providers = providers
        self._iterator = itertools.cycle(self.providers)

    def get_next_provider(self) -> str:
        return next(self._iterator)

balancer = RoundRobinBalancer(settings.PROVIDERS)
