"""Developer scripts — the write register and the hardware exercise script.

Not part of the shipped integration: HACS ships `custom_components/` only, and
nothing here is imported at runtime. It is a package rather than a loose folder
because `tests/test_write_classification.py` imports `scripts.write_classification`
to assert that every write command is classified (`dev_standards.md` §22).
"""
