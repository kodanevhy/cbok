from __future__ import annotations

import argparse
import configparser
from dataclasses import dataclass
import os
import re
import subprocess
from pathlib import Path


DEFAULT_CODE_DIRS = ("cm", "me")
DEFAULT_CBOK_REPO = "https://github.com/kodanevhy/cbok.git"
CONTEXT_FILE = ".cbok-workspace"
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class WorkspaceLayoutError(Exception):
    pass


@dataclass(frozen=True)
class WorkspaceContext:
    root: str
    editor: str
    company: str


def source_root() -> str:
    return str(Path(__file__).resolve().parent.parent)


def _realpath(path: str | Path) -> str:
    return os.path.realpath(os.path.abspath(os.path.expanduser(os.path.expandvars(str(path)))))


def _workspace_path(workspace: str | Path) -> Path:
    if not str(workspace or "").strip():
        raise WorkspaceLayoutError("WORKSPACE is required")
    return Path(_realpath(workspace))


def cbok_home_from_workspace(workspace: str | Path) -> str:
    return str(_workspace_path(workspace) / "cbok")


def is_cbok_home(path: str | Path) -> bool:
    root = Path(path)
    return (root / "cbok").is_dir() and (root / "scriptlet").is_dir()


def resolve_cbok_home(
    workspace: str | Path | None,
    env: dict[str, str] | None = None,
    fallback_source_root: str | None = None,
) -> str:
    env = os.environ if env is None else env
    env_home = (env.get("CBOK_HOME") or "").strip()
    if env_home:
        return _realpath(env_home)

    workspace_home = ""
    if str(workspace or "").strip():
        workspace_home = cbok_home_from_workspace(workspace)
        if is_cbok_home(workspace_home):
            return _realpath(workspace_home)

    current_source = fallback_source_root or source_root()
    if is_cbok_home(current_source):
        return _realpath(current_source)

    return _realpath(workspace_home or current_source)


def _require_initialized(root: Path) -> None:
    if not is_cbok_home(root / "cbok"):
        raise WorkspaceLayoutError("workspace is not initialized; run cbok workspace init first")


def _context_path(root: Path) -> Path:
    return Path(resolve_cbok_home(root)) / CONTEXT_FILE


def _validate_name(kind: str, value: str) -> str:
    name = (value or "").strip()
    if not name or not _NAME_PATTERN.match(name):
        raise WorkspaceLayoutError(f"invalid {kind}: {value}")
    return name


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def _ensure_dir(path: Path, label: str) -> None:
    if path.exists() and not path.is_dir():
        raise WorkspaceLayoutError(f"{label} exists but is not a directory: {path}")
    parent = path.parent
    if parent.exists() and not parent.is_dir():
        raise WorkspaceLayoutError(f"{label} parent exists but is not a directory: {parent}")
    path.mkdir(parents=True, exist_ok=True)


def _write_default_cbok_conf(cbok_home: Path, workspace_root: Path) -> None:
    if not cbok_home.is_dir():
        return
    conf_path = cbok_home / "cbok.conf"
    if conf_path.exists():
        return
    conf_path.write_text(
        "[default]\n"
        f"workspace = {workspace_root}\n"
        "debug = true\n"
        "log_dir = /var/log/\n",
        encoding="utf-8",
    )


def _initialized_editors(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    editors = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.name == "cbok" or not path.is_dir():
            continue
        if all((path / name).is_dir() for name in DEFAULT_CODE_DIRS):
            editors.append(path.name)
    return editors


def _company_path(root: Path, editor: str, company: str) -> Path:
    return root / editor / company


def init_workspace(
    workspace: str | Path,
    repo: str = "",
    clone: bool = False,
    runner=subprocess.run,
) -> None:
    root = _workspace_path(workspace)
    _ensure_dir(root, "workspace")

    cbok_home = root / "cbok"
    if cbok_home.exists():
        if not cbok_home.is_dir():
            raise WorkspaceLayoutError(f"cbok home exists but is not a directory: {cbok_home}")
        if not is_cbok_home(cbok_home):
            raise WorkspaceLayoutError(f"cbok home already exists: {cbok_home}")
    elif clone:
        repo = (repo or DEFAULT_CBOK_REPO).strip()
        if not repo:
            raise WorkspaceLayoutError("CBOK_REPO is required when cloning cbok")
        runner(["git", "clone", repo, str(cbok_home)], check=True)
    else:
        raise WorkspaceLayoutError(f"cbok home does not exist: {cbok_home}")

    _write_default_cbok_conf(cbok_home, root)


def init_editor(workspace: str | Path, editor: str) -> None:
    root = _workspace_path(workspace)
    _require_initialized(root)
    editor = _validate_name("editor", editor)

    for name in DEFAULT_CODE_DIRS:
        _ensure_dir(root / editor / name, f"{editor}/{name}")


def init_company(workspace: str | Path, company: str) -> None:
    root = _workspace_path(workspace)
    _require_initialized(root)
    company = _validate_name("company", company)

    editors = _initialized_editors(root)
    if not editors:
        raise WorkspaceLayoutError("no initialized editors; run cbok workspace init_editor first")

    for editor in editors:
        _ensure_dir(root / editor / company, f"{editor}/{company}")


def init_project(
    workspace: str | Path,
    editor: str,
    company: str,
    project: str,
    repo: str = "",
    runner=subprocess.run,
) -> str:
    root = _workspace_path(workspace)
    _require_initialized(root)
    editor = _validate_name("editor", editor)
    company = _validate_name("company", company)
    project = _validate_name("project", project)

    company_home = _company_path(root, editor, company)
    if not company_home.is_dir():
        raise WorkspaceLayoutError(f"company is not initialized: {company}")

    project_home = company_home / project
    project_path = _realpath(project_home)
    repo = repo.strip()
    if repo:
        if project_home.exists():
            raise WorkspaceLayoutError(f"project path already exists: {project_home}")
        runner(["git", "clone", repo, project_path], check=True)
        return project_path

    if project_home.exists():
        if not project_home.is_dir():
            raise WorkspaceLayoutError(f"project path exists but is not a directory: {project_home}")
        if any(project_home.iterdir()) and not _is_git_repo(project_home):
            raise WorkspaceLayoutError(f"project path exists but is not a git repository: {project_home}")
        return project_path

    project_home.mkdir()
    return project_path


def use_context(workspace: str | Path, editor: str, company: str) -> WorkspaceContext:
    root = _workspace_path(workspace)
    _require_initialized(root)
    editor = _validate_name("editor", editor)
    company = _validate_name("company", company)

    company_home = _company_path(root, editor, company)
    if not company_home.is_dir():
        raise WorkspaceLayoutError(f"company is not initialized: {company}")

    parser = configparser.ConfigParser()
    parser["context"] = {
        "editor": editor,
        "company": company,
    }
    context_path = _context_path(root)
    with context_path.open("w", encoding="utf-8") as stream:
        parser.write(stream)
    return WorkspaceContext(_realpath(root), editor, company)


def current_context(workspace: str | Path) -> WorkspaceContext:
    root = _workspace_path(workspace)
    _require_initialized(root)
    context_path = _context_path(root)
    if not context_path.is_file():
        raise WorkspaceLayoutError(
            "workspace context is not configured; run cbok workspace use first"
        )

    parser = configparser.ConfigParser()
    parser.read(context_path, encoding="utf-8")
    if not parser.has_section("context"):
        raise WorkspaceLayoutError("workspace context is invalid; run cbok workspace use first")

    editor = _validate_name("editor", parser.get("context", "editor", fallback=""))
    company = _validate_name("company", parser.get("context", "company", fallback=""))
    return WorkspaceContext(_realpath(root), editor, company)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cbok.workspace")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_workspace_parser = subparsers.add_parser("init-workspace")
    init_workspace_parser.add_argument("--workspace", required=True)
    init_workspace_parser.add_argument("--repo", default="")
    init_workspace_parser.add_argument("--clone", action="store_true")

    init_editor_parser = subparsers.add_parser("init-editor")
    init_editor_parser.add_argument("--workspace", required=True)
    init_editor_parser.add_argument("--editor", required=True)

    init_company_parser = subparsers.add_parser("init-company")
    init_company_parser.add_argument("--workspace", required=True)
    init_company_parser.add_argument("--company", required=True)

    init_project_parser = subparsers.add_parser("init-project")
    init_project_parser.add_argument("--workspace", required=True)
    init_project_parser.add_argument("--editor", required=True)
    init_project_parser.add_argument("--company", required=True)
    init_project_parser.add_argument("--project", required=True)
    init_project_parser.add_argument("--repo", default="")

    use_parser = subparsers.add_parser("use")
    use_parser.add_argument("--workspace", required=True)
    use_parser.add_argument("--editor", required=True)
    use_parser.add_argument("--company", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "init-workspace":
            init_workspace(args.workspace, repo=args.repo, clone=args.clone)
        elif args.command == "init-editor":
            init_workspace(args.workspace)
            init_editor(args.workspace, args.editor)
        elif args.command == "init-company":
            init_workspace(args.workspace)
            init_company(args.workspace, args.company)
        elif args.command == "init-project":
            init_workspace(args.workspace)
            init_project(args.workspace, args.editor, args.company, args.project, repo=args.repo)
        elif args.command == "use":
            use_context(args.workspace, args.editor, args.company)
    except WorkspaceLayoutError as e:
        parser.exit(1, f"{e}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
