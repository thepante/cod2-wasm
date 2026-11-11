#!/usr/bin/env python3
"""Walk a test client into Brecourt's minefields through the real dedicated server.

Requires Docker, the native server image and the private browser archives, plus the owner's retail archive with
Brecourt for the minefields' bounds; no network. As server.cfg leaves it the minefield kills; with
scr_minefields_harmless 1 it clicks and blows up without harm. A script radiusDamage, as S&D's bomb deals, hurts
either way, and setPlayerIgnoreRadiusDamage still spares players.
"""
import argparse
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
# A first-party QA script in the bot script's slot: it adds the test client and walks it in.
CHECKS = r'''
main()
{
	level thread run();
}

check(name, ok, detail)
{
	if(ok)
		println("[minefield-qa] PASS " + name);
	else
		println("[minefield-qa] FAIL " + name + " " + detail);
}

answer(p, response)
{
	p closeMenu();
	p closeInGameMenu();
	p [[level.weapon]](response);
}

state(p)
{
	return "alive=" + isAlive(p) + " health=" + p.health + " clicked=" + isDefined(p.minefield) + " at=" + p.origin
		+ " harmless=" + getCvar("scr_minefields_harmless");
}

touching(p)
{
	minefields = getEntArray("minefield", "targetname");
	for(i = 0; i < minefields.size; i++)
	{
		if(p isTouching(minefields[i]))
			return true;
	}
	return false;
}

// The first minefield centre whose ground the client stands on inside the trigger.
findSpot(p, safe)
{
	candidates = [];
%CANDIDATES%
	for(i = 0; i < candidates.size; i++)
	{
		top = candidates[i];
		trace = bulletTrace(top, (top[0], top[1], top[2] - 4000), false, p);
		if(trace["fraction"] >= 1)
			continue;
		spot = trace["position"] + (0, 0, 1);
		p setOrigin(spot);
		wait .05;
		inside = touching(p);
		p setOrigin(safe);
		p.minefield = undefined;
		wait 1.5;
		if(inside)
			return spot;
	}
	return undefined;
}

waitAlive(p)
{
	for(i = 0; i < 60 && !isAlive(p); i++)
		wait .25;
	wait 1;
	p botStop();
}

run()
{
	wait 2;
	p = addTestClient();
	wait 2;
	p [[level.allies]]();
	wait .5;
	answer(p, "class,m1garand_mp,colt_mp,frag_grenade_american_mp,smoke_grenade_american_mp");
	wait 2;
	p botStop();
	safe = p.origin;
	check("spawns", isAlive(p) && !touching(p), state(p));

	spot = findSpot(p, safe);
	check("finds-a-minefield", isDefined(spot), state(p));
	if(!isDefined(spot))
	{
		println("[minefield-qa] DONE");
		return;
	}

	// The default server.cfg leaves: the retail minefield, which kills.
	check("defaults-to-killing", getCvarInt("scr_minefields_harmless") == 0, state(p));
	full = p.health;
	p setOrigin(spot);
	wait .3;
	check("default-clicks", isDefined(p.minefield) && isAlive(p) && p.health == full, state(p));
	wait 1.5;
	check("default-kills", !isAlive(p), state(p));
	waitAlive(p);
	check("respawns-after-the-minefield", isAlive(p) && !touching(p), state(p));

	setCvar("scr_minefields_harmless", "1");
	full = p.health;
	p setOrigin(spot);
	wait .3;
	check("harmless-clicks", isDefined(p.minefield), state(p));
	wait 1.5;
	check("harmless-spares", isAlive(p) && p.health == full, state(p));
	p setOrigin(safe);
	wait 1.5;
	check("harmless-leaves-whole", isAlive(p) && p.health == full && !isDefined(p.minefield), state(p));

	// The switch is the minefields' alone: another script blast, as S&D's bomb, still hurts.
	radiusDamage(p.origin + (0, 0, 32), 100, 40, 40);
	wait .1;
	check("script-blast-hurts", isAlive(p) && p.health < full, state(p));
	hurt = p.health;
	setPlayerIgnoreRadiusDamage(true);
	radiusDamage(p.origin + (0, 0, 32), 100, 40, 40);
	setPlayerIgnoreRadiusDamage(false);
	wait .1;
	check("ignored-blast-spares", isAlive(p) && p.health == hurt, state(p));
	radiusDamage(p.origin + (0, 0, 32), 100, 2000, 2000);
	wait .1;
	check("script-blast-kills", !isAlive(p), state(p));
	waitAlive(p);
	check("respawns-after-the-blast", isAlive(p), state(p));
	println("[minefield-qa] DONE");
}
'''
EXPECTED = 13
MODELS_LUMP = 35


def minefield_tops(bsp: bytes) -> list:
    """Each minefield trigger's centre at its top, from the map's entities and its brush models' bounds."""
    assert bsp[:4] == b'IBSP' and struct.unpack_from('<i', bsp, 4)[0] == 4
    length, offset = struct.unpack_from('<ii', bsp, 8 + MODELS_LUMP * 8)
    assert length % 48 == 0
    models = [int(re.search(rb'"model" "\*(\d+)"', entity).group(1)) for entity in re.findall(rb'\{[^{}]*\}', bsp)
              if b'"targetname" "minefield"' in entity]
    tops = []
    for model in models:
        assert model < length // 48
        x0, y0, z0, x1, y1, z1 = struct.unpack_from('<6f', bsp, offset + model * 48)
        tops.append(((x0 + x1) / 2, (y0 + y1) / 2, z1))
    return tops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='local/cod2-native-server:dev')
    parser.add_argument('--assets', type=Path, default=ROOT / 'data/browser/main')
    parser.add_argument('--retail', type=Path, default=ROOT / 'data/main/iw_03.iwd')
    parser.add_argument('--binary', type=Path, default=ROOT / 'out/cod2-native/cod2_lnxded')
    parser.add_argument('--classes', type=Path, default=ROOT / 'downstream/server/browser_classes.gsc')
    parser.add_argument('--log', type=Path, default=ROOT / 'out/minefields-runtime/server.log')
    args = parser.parse_args()
    for item in (args.assets, args.retail, args.binary, args.classes):
        if not item.exists():
            parser.error(f'missing {item}')
    with zipfile.ZipFile(args.retail) as archive:
        tops = minefield_tops(archive.read('maps/mp/mp_brecourt.d3dbsp'))
    assert tops, 'no minefields on Brecourt'
    candidates = '\n'.join(f'\tcandidates[candidates.size] = ({x:.1f}, {y:.1f}, {z:.1f});' for x, y, z in tops)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    name = 'cod2-minefield-qa-' + uuid.uuid4().hex[:10]
    log = ''
    with tempfile.TemporaryDirectory(prefix='cod2-minefield-qa-') as directory:
        checks = Path(directory) / 'checks.gsc'
        checks.write_text(CHECKS.replace('%CANDIDATES%', candidates))
        try:
            subprocess.run(['docker', 'run', '-d', '--name', name, '--platform', 'linux/amd64', '--network', 'none',
                            '--ulimit', 'core=0', '--read-only', '--tmpfs', '/profile:uid=1000,gid=1000,size=32m',
                            '--tmpfs', '/tmp:size=16m', '-v', f'{args.assets.resolve()}:/game/main:ro',
                            '-v', f'{args.binary.resolve()}:/qa-engine:ro',
                            '-v', f'{args.classes.resolve()}:/qa-classes.gsc:ro',
                            '-v', f'{checks}:/qa-checks.gsc:ro', '-v', f'{(ROOT / "server.cfg").resolve()}:/qa-server.cfg:ro',
                            '--entrypoint', '/bin/sh', args.image, '-c',
                            'mkdir -p /profile/raw/maps/mp; cp /qa-classes.gsc /profile/raw/maps/mp/browser_classes.gsc; '
                            'cp /qa-checks.gsc /profile/raw/maps/mp/browser_bots.gsc; cp /qa-server.cfg /profile/raw/server.cfg; '
                            'exec /qa-engine +set dedicated 1 +set fs_basepath /game +set fs_homepath /profile '
                            '+set net_ip 127.0.0.1 +set sv_maxclients 16 +exec server.cfg '
                            '+set scr_bot_count 1 +set scr_forcerespawn 1 +set scr_tdm_timelimit 0 '
                            '+set scr_tdm_scorelimit 0 +set g_gametype tdm +map mp_brecourt'],
                           check=True, capture_output=True)
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                log = subprocess.run(['docker', 'logs', name], capture_output=True, text=True).stdout
                if '[minefield-qa] DONE' in log or re.search(r'script (?:compile|runtime) error|Error during initialization', log, re.I):
                    break
                time.sleep(1)
        finally:
            log = subprocess.run(['docker', 'logs', name], capture_output=True, text=True).stdout or log
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True)
    args.log.write_text(log)
    errors = re.findall(r'.*script (?:compile|runtime) error.*', log, re.I)
    failures = re.findall(r'\[minefield-qa\] FAIL .*', log)
    passes = re.findall(r'\[minefield-qa\] PASS (\S+)', log)
    if errors or failures or len(passes) != EXPECTED:
        raise SystemExit('\n'.join(errors + failures) + f'\n{len(passes)}/{EXPECTED} passed; log: {args.log}')
    print(f'PASS: {EXPECTED} minefield checks on mp_brecourt through the dedicated server: by default a minefield '
          'clicks and kills, with scr_minefields_harmless 1 it clicks and spares, a script blast still hurts and '
          'kills, setPlayerIgnoreRadiusDamage still spares, and the client respawns after each death')


if __name__ == '__main__':
    main()
