"""Dynamic provider discovery and safe instantiation."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Type

import sophyane.providers
from sophyane.logging_config import configure_logging
from sophyane.providers.base import Provider


LOGGER = configure_logging()


class PluginLoader:
    def __init__(self) -> None:
        self._providers: dict[str, Type[Provider]] = {}
        self.errors: dict[str, str] = {}

    def discover(self) -> dict[str, Type[Provider]]:
        self._providers.clear()
        self.errors.clear()

        ignored_modules = {
            "base",
            "http",
            "openai_compatible",
            "fallback",  # composite wrapper, not a leaf plugin
        }

        for module_info in pkgutil.iter_modules(
            sophyane.providers.__path__
        ):
            module_name = module_info.name

            if module_name.startswith("_"):
                continue

            if module_name in ignored_modules:
                continue

            qualified_name = f"sophyane.providers.{module_name}"

            try:
                module = importlib.import_module(qualified_name)
            except Exception as error:
                self.errors[module_name] = str(error)
                LOGGER.exception(
                    "Provider plugin import failed: %s",
                    qualified_name,
                )
                continue

            for _, candidate in inspect.getmembers(
                module,
                inspect.isclass,
            ):
                if candidate is Provider:
                    continue

                if not issubclass(candidate, Provider):
                    continue

                if candidate.__module__ != module.__name__:
                    continue

                metadata = getattr(candidate, "metadata", None)

                if not metadata:
                    continue

                self._providers[metadata.provider_id] = candidate

        return dict(self._providers)

    @property
    def providers(self) -> dict[str, Type[Provider]]:
        if not self._providers:
            self.discover()

        return dict(self._providers)

    def create(
        self,
        provider_id: str,
        **kwargs: object,
    ) -> Provider:
        provider_class = self.providers.get(provider_id)

        if provider_class is None:
            raise KeyError(f"Unknown provider: {provider_id}")

        try:
            signature = inspect.signature(provider_class.__init__)
            signature.bind_partial(None, **kwargs)
        except TypeError as error:
            LOGGER.exception(
                "Invalid arguments for provider %s; signature=%s; "
                "arguments=%s",
                provider_id,
                inspect.signature(provider_class.__init__),
                sorted(kwargs),
            )
            raise TypeError(
                f"{provider_class.__name__} rejected its configuration. "
                f"Expected signature: "
                f"{inspect.signature(provider_class.__init__)}. "
                f"Received: {sorted(kwargs)}. Original error: {error}"
            ) from error

        try:
            return provider_class(**kwargs)
        except Exception:
            LOGGER.exception(
                "Provider initialization failed: %s",
                provider_id,
            )
            raise
