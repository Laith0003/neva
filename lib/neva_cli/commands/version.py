"""neva version"""
import os

HELP = "print the Neva version"


def run(args):
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
    print(open(os.path.join(root, "VERSION")).read().strip())
    return 0
