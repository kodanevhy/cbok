import argparse
from cbok.conf import config
from cbok.conf.generator import ConfigGenerator

parser = argparse.ArgumentParser(
    description="Generate default cbok.conf"
)
parser.add_argument(
    "-o", "--output",
    default="cbok.conf",
    help="Output config file path"
)
parser.add_argument(
    "-f", "--force",
    action="store_true",
    help="Overwrite existing config file without prompt"
)
parser.add_argument(
    "--editor",
    help="Editor directory for managed projects",
)

args = parser.parse_args()

ConfigGenerator(config.ALL_GROUPS).generate(
    args.output,
    force=args.force,
    overrides={("default", "editor"): args.editor} if args.editor is not None else None,
)
