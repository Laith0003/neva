"""neva omni: push the compiled brain pack to the omni worker, or sync its threads into the vault."""
import os
from neva_omni.brainpack import describe_sources, provider_line
from neva_omni.sync import load_pack, push_pack, sync_threads

HELP = "push the brain pack to the omni worker, or sync its threads into the vault"

DEFAULT_PACK = os.path.expanduser("~/.local/share/neva/brainpack.json")


def add_arguments(p):
    p.add_argument("action", choices=["push", "sync"],
                    help="push: upload the compiled brain pack; sync: write worker threads into the vault")
    p.add_argument("--url", default=os.environ.get("NEVA_OMNI_URL", ""),
                   help="the worker's https address (default: $NEVA_OMNI_URL)")
    p.add_argument("--pack", default=DEFAULT_PACK, help=f"the compiled pack (default: {DEFAULT_PACK})")
    p.add_argument("--vault", default=os.environ.get("NEVA_VAULT", ""),
                   help="vault to write synced threads into (default: $NEVA_VAULT)")
    # The token is read from the environment by name and never taken as a flag: a flag value
    # lands in shell history and in ps output.
    p.add_argument("--token-env", default="NEVA_OMNI_TOKEN",
                   help="name of the env var holding the worker's DEVICE_TOKEN (default: NEVA_OMNI_TOKEN)")


def run(args):
    token = os.environ.get(args.token_env, "")
    try:
        if args.action == "push":
            pack = load_pack(args.pack)
            lines = describe_sources(pack)
            print(f"omni push: {args.pack} holds these files:")
            print("\n".join(lines))
            print(f"omni push: {provider_line()}")
            result = push_pack(args.url, token, pack)
        else:
            written = sync_threads(args.url, token, args.vault)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"omni {args.action}: {e}")
        return 2

    if args.action == "push":
        # push_pack has already refused any reply that does not confirm every tier it sent.
        tiers = ", ".join(f"{name} {chars} chars" for name, chars in sorted(result["tiers"].items()))
        print(f"omni push: {tiers} -> {args.url.rstrip('/')}/brainpack")
    else:
        print(f"omni sync: {len(written)} thread(s) -> {args.vault.rstrip('/')}/06 Memory/Conversations")
    return 0
