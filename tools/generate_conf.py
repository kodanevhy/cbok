import argparse
from cbok.conf.config import ALL_GROUPS
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

args = parser.parse_args()

ConfigGenerator(ALL_GROUPS).generate(
    args.output,
    force=args.force
)
