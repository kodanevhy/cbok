from pathlib import Path

class ConfigGenerator:
    def __init__(self, groups):
        self.groups = groups

    def generate(self, path: str, force: bool = False):
        path = Path(path)

        if path.exists() and not force:
            answer = input(
                f"Config file '{path}' already exists. Overwrite? [y/N]: "
            ).strip().lower()

            if answer not in ("y", "yes"):
                print("Aborted.")
                return

        lines = []

        for group in self.groups:
            lines.append(f"[{group.name}]")

            for opt in group.options:
                if opt.help:
                    lines.append(f"# {opt.help}")

                value = opt.default
                if isinstance(value, bool):
                    value = str(value).lower()
                elif value is None:
                    value = ""

                lines.append(f"{opt.name} = {value}")

            lines.append("")

        path.write_text("\n".join(lines))
        print(f"Config written to {path}")
