"""python3 -m neva_engine tick --config engine.json [--dry-run] [--out DIR]"""
import argparse
import sys

from . import tick

parser = argparse.ArgumentParser(prog="neva_engine", description="One look at the owner's sources.")
parser.add_argument("command", choices=["tick"])
parser.add_argument("--config", required=True, help="the engine config, JSON")
parser.add_argument("--dry-run", action="store_true", help="print today.json, store nothing")
parser.add_argument("--out", help="runtime folder, instead of the one in the config")
args = parser.parse_args()
sys.exit(tick.run(args.config, dry_run=args.dry_run, out=args.out))
