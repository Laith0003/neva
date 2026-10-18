"""neva brainpack: compile the files listed in the omni config into a JSON brain pack."""
import json, os
from neva_omni.safe_write import atomic_write
from neva_omni.brainpack import (CONFIG_ENV, DEFAULT_CONFIG, TIERS, compile_pack, config_path,
                                 load_config, provider_line, select_sources)

HELP = "compile the files listed in the omni config into a tiered brain pack"


def add_arguments(p):
    p.add_argument("--config", default=None,
                   help=f"the omni config with the include list (default: ${CONFIG_ENV} or {DEFAULT_CONFIG})")
    p.add_argument("--out", default=os.path.join("~", ".local", "share", "neva", "brainpack.json"))


def run(args):
    path = config_path(args.config)
    try:
        included, skipped = select_sources(load_config(path), os.path.dirname(path))
    except ValueError as error:
        print(f"brainpack: {error}")
        return 2

    print(f"brainpack: config {path}")
    for source in included:
        print(f"  {source} ({os.path.getsize(source)} bytes)")
    for source, reason in skipped:
        print(f"  skipped {source}: {reason}")
    if not included:
        print(f'brainpack: nothing to compile: the "include" list in {path} is empty. '
              'Add the paths or globs to send, for example {"include": ["~/notes/rules/*.md"]}. Nothing was written.')
        return 2

    try:
        pack = compile_pack({"include": included}, TIERS)
    except (ValueError, OSError) as error:
        print(f"brainpack: {error}. Nothing was written.")
        return 2

    output = os.path.abspath(os.path.expandvars(os.path.expanduser(args.out)))
    try:
        atomic_write(os.path.dirname(output), output, json.dumps(pack, ensure_ascii=False))
    except (ValueError, OSError) as error:
        print("brainpack: {}".format(error))
        return 2
    sizes = ', '.join('{} {} chars'.format(k, v['chars']) for k, v in pack['tiers'].items())
    print("brainpack: {} -> {}".format(sizes, output))
    print(f"brainpack: {provider_line()}")
    return 0
