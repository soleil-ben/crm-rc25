"""Vendor pricing data: the tariff workbook reader and its reviewed semantics (Phase 13A).

Everything in this package is pure: no database, no network, no clock. ``kango_workbook``
turns a workbook into typed rows with the sheet and cell each one came from;
``kango_semantics`` holds the reviewed meaning of the surcharge rows and the fees the
vendor writes in prose. ``app/services/tariff_import_service.py`` is what persists the
result.
"""
