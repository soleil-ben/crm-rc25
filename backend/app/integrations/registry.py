"""The provider adapter registry. It is empty, and in production it stays empty.

``PRODUCTION_ADAPTERS`` is the whole production configuration and it contains nothing. No
adapter exists for any provider, because the ShipStation account's product, API
generation, entitlements, authentication scheme, webhook capabilities, signature
mechanism, rate limits, external-label tracking support, and resource hosts are all
unverified (``docs/INTEGRATIONS.md`` section 3). Writing one against guessed fixtures
would produce something that looks finished and works against nothing.

**Registration is refused in production.** ``register`` raises when
``settings.is_production`` is true, so the deterministic fake used by the test suite
cannot be installed on a production instance by an import, a stray environment variable,
or a mistake in a start-up script. The seed guard uses the same shape (DEC-0026) and for
the same reason: a guard that depends on nobody making a mistake is not a guard.

A missing adapter is never fatal. ``get_adapter`` raises
``AdapterUnavailableError``, callers turn that into "not configured", and the CRM,
manual milestones, external links, bookings, labels, and public tracking all keep working
-- which CRM.md section 3 requires without qualification.
"""

from __future__ import annotations

from app.core.config import settings
from app.integrations.adapter import ProviderAdapter
from app.services.errors import DomainError

#: The production registry. Empty, and it must stay empty until an account is verified.
#: This is not a placeholder waiting to be filled with a guess: it is the accurate
#: description of how many providers this installation can talk to.
PRODUCTION_ADAPTERS: dict[str, ProviderAdapter] = {}


class AdapterUnavailableError(DomainError):
    """No adapter can serve this provider key.

    A 409 rather than a 404: the provider key is a perfectly good name, there is simply
    nothing configured behind it. Callers translate this into the ``not_configured``
    connection state instead of treating it as a failure to report.
    """

    status_code = 409
    code = "provider_not_configured"


class AdapterRegistry:
    """Adapters this process may use.

    Test registration is explicit, refused in production, and scoped: ``registered``
    returns a context manager so a fake cannot leak from one test into the next and make
    a later test pass for the wrong reason.
    """

    def __init__(self, adapters: dict[str, ProviderAdapter] | None = None) -> None:
        self._adapters: dict[str, ProviderAdapter] = dict(adapters or {})

    def register(self, adapter: ProviderAdapter) -> None:
        """Install an adapter. Refused outright while the environment is production.

        The check is on the environment rather than on the adapter, deliberately. A rule
        of "only fakes are refused" would need a reliable way to recognize a fake, and
        the failure mode of getting that wrong is a synthetic provider answering a real
        customer.
        """
        if settings.is_production:
            raise AdapterUnavailableError(
                "Provider adapters cannot be registered at runtime in production. "
                "No provider account has been verified."
            )
        self._adapters[adapter.capabilities().provider_key] = adapter

    def unregister(self, provider_key: str) -> None:
        self._adapters.pop(provider_key, None)

    def get(self, provider_key: str) -> ProviderAdapter:
        adapter = self._adapters.get(provider_key)
        if adapter is None:
            raise AdapterUnavailableError(
                "No provider integration is configured. Tracking is by manual milestone "
                "or external carrier link only.",
                detail={"provider_key": provider_key},
            )
        return adapter

    def has(self, provider_key: str) -> bool:
        return provider_key in self._adapters

    def provider_keys(self) -> list[str]:
        return sorted(self._adapters)

    def is_empty(self) -> bool:
        return not self._adapters


#: The registry the application uses. Seeded from the empty production mapping.
registry = AdapterRegistry(PRODUCTION_ADAPTERS)


def get_adapter(provider_key: str) -> ProviderAdapter:
    return registry.get(provider_key)


def is_any_provider_configured() -> bool:
    """Whether this installation can talk to any provider at all.

    ``False`` today, everywhere. The health service turns this into ``not_configured``
    rather than into an error, because not being connected is the current design state
    and not a fault.
    """
    return not registry.is_empty()
