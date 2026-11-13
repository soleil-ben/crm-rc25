"""Which vendor product a Solaris service is priced through (OD-43, DEC-0175).

One table, kept here rather than in the database schema because it is a reading of the
vendor's product catalogue, like the rest of ``app/pricing``: the importer turns it into
``service_vendor_products`` rows for every tariff version it imports, per origin, and the
rows are what the application reads. Changing the mapping is a new import, and a quotation
records which rows it used.

**Air only.** Under the confirmed method (v0.7, DEC-0265) Sea is priced on the sea vendor's
own rate and UPS manually, so neither needs a Kango product; under the RC-UAT-25 method they
have no mapping and the engine says why.
"""

from __future__ import annotations

from app.core.enums import SolarisService, TariffLastMile

#: Solaris service → (vendor product code, last mile). The product code is the vendor's
#: own and is matched against ``tariff_products.code`` exactly.
AIR_SERVICE_PRODUCTS: dict[SolarisService, tuple[str, TariffLastMile]] = {
    SolarisService.AIR_STANDARD: ("AIR-CAD", TariffLastMile.PUROLATOR_GROUND),
    SolarisService.AIR_EXPRESS: ("AIR-CAD EXPRESS", TariffLastMile.PUROLATOR_EXPRESS),
}

#: Services with no mapping today, and the reason the engine will give.
UNMAPPED_SERVICE_REASONS: dict[SolarisService, str] = {
    SolarisService.SEA: (
        "Sea has no Kango product: it is priced on the sea vendor's rate under the confirmed "
        "method."
    ),
    SolarisService.UPS: (
        "UPS has no Kango product: it is priced manually under the confirmed method."
    ),
    SolarisService.AIR_CARGO: (
        "Air Cargo has no Kango product: it is priced manually under the confirmed method."
    ),
}
