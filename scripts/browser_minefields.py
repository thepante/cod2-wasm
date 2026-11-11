"""The maps' minefields: they kill as in retail, or with scr_minefields_harmless 1 click and blow up without harm."""

SCRIPT = 'maps/mp/_minefields.gsc'
RETAIL_DAMAGE = b'\t\tradiusDamage(origin, range, maxdamage, mindamage);'
HARMLESS_CVAR = 'scr_minefields_harmless'


def apply_minefields(name: str, original: bytes) -> bytes:
    """The minefield's blast deals its damage unless HARMLESS_CVAR is set."""
    if name != SCRIPT:
        return original
    if original.count(RETAIL_DAMAGE) != 1:
        raise ValueError('Unexpected retail minefield damage')
    newline = b'\r\n' if b'\r\n' in original else b'\n'
    return original.replace(RETAIL_DAMAGE, b'\t\tif(!getCvarInt("%s"))%s\t%s' % (
        HARMLESS_CVAR.encode(), newline, RETAIL_DAMAGE))
