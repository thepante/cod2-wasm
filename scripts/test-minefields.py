#!/usr/bin/env python3
"""The maps' minefields: the script's harmless switch, the engine's world attacker for script radiusDamage and,
with the owner's files, the retail script it relies on."""
import re
import sys
import types
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / 'scripts'))
import browser_minefields  # noqa: E402

KILL = (b'\t\tplayfx(level._effect["mine_explosion"], origin);\r\n'
        b'\t\tradiusDamage(origin, range, maxdamage, mindamage);\r\n\t}\r\n')


def check(module):
    """The blast's damage behind the switch, in the script's own line endings; nothing else changed."""
    for newline in (b'\r\n', b'\n'):
        retail = KILL.replace(b'\r\n', newline)
        patched = module.apply_minefields('maps/mp/_minefields.gsc', retail)
        assert patched == retail.replace(
            b'\t\tradiusDamage(', b'\t\tif(!getCvarInt("scr_minefields_harmless"))' + newline + b'\t\t\tradiusDamage('), patched
        for unexpected in (retail.replace(b'maxdamage, mindamage', b'mindamage, maxdamage'), retail + retail):
            try:
                module.apply_minefields('maps/mp/_minefields.gsc', unexpected)
            except ValueError:
                continue
            raise AssertionError('unexpected retail minefield accepted')
    for name in ('maps/mp/gametypes/sd.gsc', 'maps/mp/mp_brecourt.gsc', 'maps/_minefields.gsc'):
        assert module.apply_minefields(name, KILL) == KILL, name


check(browser_minefields)
# Script radiusDamage (the minefields, S&D's bomb) hurts as the world: G_RadiusDamage deals nothing without an
# attacker.
engine = (root / 'src/PC/game_mp/g_scr_main_mp.c').read_text()
call = re.search(r'void GScr_RadiusDamage\(void\)\n\{.*?\n    (G_RadiusDamage\([^;]*\));', engine, re.S).group(1)
assert call == 'G_RadiusDamage(origin, &g_entities[1022], &g_entities[1022], max_damage, min_damage, range, NULL, 0xe)', call
combat = (root / 'src/PC/game_mp/g_combat_mp.c').read_text()
assert re.search(r'G_RadiusDamage\([^)]*\)\n\{.*?if \(attacker == NULL\) \{\n\s*hitClient = 0;\n\s*goto done;', combat, re.S)

MUTANTS = [
    ('    if name != SCRIPT:\n        return original\n', ''),
    ("    if original.count(RETAIL_DAMAGE) != 1:\n        raise ValueError('Unexpected retail minefield damage')\n", ''),
    ("HARMLESS_CVAR = 'scr_minefields_harmless'", "HARMLESS_CVAR = 'scr_minefields'"),
    ("b'\\t\\tif(!getCvarInt(", "b'\\t\\tif(getCvarInt("),
    ("newline = b'\\r\\n' if b'\\r\\n' in original else b'\\n'", "newline = b'\\n'"),
]
source = (root / 'scripts/browser_minefields.py').read_text()
for old, new in MUTANTS:
    assert source.count(old) == 1, old
    mutant = types.ModuleType('mutant')
    exec(compile(source.replace(old, new), 'browser_minefields.py', 'exec'), mutant.__dict__)
    try:
        check(mutant)
    except (AssertionError, ValueError):
        continue
    raise AssertionError('mutant survived: ' + new)

retail = root / 'data/main/iw_07.iwd'
if retail.exists():
    with zipfile.ZipFile(retail) as archive:
        original = archive.read('maps/mp/_minefields.gsc')
    patched = browser_minefields.apply_minefields('maps/mp/_minefields.gsc', original)
    assert patched.count(b'if(!getCvarInt("scr_minefields_harmless"))\r\n\t\t\tradiusDamage(') == 1
    print('PASS: minefields kill unless scr_minefields_harmless is set, script radiusDamage hurts as the world; '
          f'{len(MUTANTS)} mutants fail; the retail script takes the patch')
else:
    print(f'PASS: minefield patch and engine attacker; {len(MUTANTS)} mutants fail; retail script not checked '
          '(no owner files)')
