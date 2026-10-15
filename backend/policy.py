import os
import shlex
import fcntl
from contextlib import contextmanager
from typing import Iterable, List, Tuple


class PolicyError(ValueError):
    pass


class ApprovalRequired(PolicyError):
    def __init__(self, operation: str, reason: str, risk: str = "confirm"):
        super().__init__(reason)
        self.operation = operation
        self.reason = reason
        self.risk = risk


class WorkspacePolicy:
    """Path and command guard for the two local execution modes.

    safe: command execution requires approval unless a
    command is explicitly allowlisted. divergent: ordinary commands are free
    to run; only high-risk commands require approval. Blocked commands remain
    blocked in both modes.
    """

    MODES = ("safe", "divergent")

    def __init__(self, root: str, ignored: Iterable[str] = (".git", ".codespider", ".venv", "venv", "node_modules", "target", "dist", "__pycache__"), mode: str = "safe", command_allowlist: Iterable[str] = ()):
        self.root = os.path.realpath(root)
        self.ignored = tuple(ignored)
        self.mode = mode if mode in self.MODES else "safe"
        self.command_allowlist = tuple(item.strip() for item in command_allowlist if item and item.strip())

    def resolve(self, relative_path: str) -> str:
        if not relative_path or os.path.isabs(relative_path):
            raise PolicyError("path must be a non-empty relative path")
        candidate = os.path.realpath(os.path.join(self.root, relative_path))
        if candidate != self.root and not candidate.startswith(self.root + os.sep):
            raise PolicyError("path escapes workspace root")
        return candidate

    def is_ignored(self, relative_path: str) -> bool:
        parts = relative_path.replace("\\", "/").split("/")
        normalized = '/'.join(part for part in parts if part != '.')
        return any(part in self.ignored for part in parts) or normalized == 'vendor/codespider' or normalized.startswith('vendor/codespider/')

    @contextmanager
    def open_file(self, relative_path: str, mode: str = "r", create_parents: bool = False):
        """Resolve links within the workspace, then open without following races.

        Directory-relative descriptors keep a symlink swap between validation
        and open from redirecting a tool outside the workspace.
        """
        target = self.resolve(relative_path)
        parts = os.path.relpath(target, self.root).split(os.sep)
        if parts == ["."] or mode not in ("r", "rb", "w", "r+", "x"):
            raise PolicyError("invalid file operation")
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                if create_parents:
                    try:
                        os.mkdir(part, dir_fd=directory)
                    except FileExistsError:
                        pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            flags = os.O_RDONLY if mode in ("r", "rb") else (os.O_RDWR if mode == "r+" else os.O_WRONLY | os.O_CREAT)
            if mode == "x":
                flags |= os.O_EXCL
            descriptor = os.open(parts[-1], flags | os.O_NOFOLLOW, 0o666, dir_fd=directory)
            with os.fdopen(descriptor, mode, **({"encoding": "utf-8"} if mode != "rb" else {})) as handle:
                # Never truncate before acquiring the lock. All tools use the
                # same inode lock, including separate Agent processes.
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH if mode in ("r", "rb") else fcntl.LOCK_EX)
                if mode == "w":
                    handle.truncate(0)
                yield handle
        finally:
            os.close(directory)

    def is_command_allowlisted(self, command: str) -> bool:
        normalized = command.strip()
        return any(normalized == entry or normalized.startswith(entry + " ") for entry in self.command_allowlist)

    def command_risk(self, command: str) -> str:
        if not isinstance(command, str):
            raise PolicyError("command must be a string")
        tokens = shlex.split(command)
        if not tokens:
            raise PolicyError("command cannot be empty")
        lowered = command.lower()
        blocked = ("mkfs", "shutdown", "> /dev/", "format c:")
        high_risk = ("rm -rf", "sudo", "git reset --hard", "git clean -fd", "drop database", "truncate table")
        network_or_mutating = ("pip install", "npm install", "pnpm install", "yarn add", "curl ", "wget ", "docker push")
        if any(item in lowered for item in blocked):
            return "blocked"
        # Classify destructive executables independently of option spelling or
        # order (rm -fr, rm -r -f, /bin/rm --recursive, env ... rm, etc.).
        names = [os.path.basename(token).lower() for token in tokens]
        if any(name in ("rm", "rmdir", "sudo", "doas") for name in names):
            return "high"
        if "git" in names:
            arguments = tokens[names.index("git") + 1:]
            if ("reset" in arguments and "--hard" in arguments) or "clean" in arguments:
                return "high"
        # Shell command strings remain arguments because subprocess uses argv;
        # inspect their contents before allowing an explicitly invoked shell.
        if names[0] in ("sh", "bash", "zsh", "dash", "ksh"):
            for index, token in enumerate(tokens[1:], 1):
                if token.startswith("-") and "c" in token and index + 1 < len(tokens):
                    return self.command_risk(tokens[index + 1])
        if any(item in lowered for item in high_risk):
            return "high"
        if any(item in lowered for item in network_or_mutating):
            return "confirm"
        return "low"

    def validate_command(self, command: str, approved: bool = False) -> Tuple[str, List[str]]:
        if type(approved) is not bool:
            raise PolicyError("approved must be a boolean")
        risk = self.command_risk(command)
        if risk == "blocked":
            raise PolicyError("command is blocked by local policy")
        if approved:
            return risk, shlex.split(command)
        if risk == "high":
            raise ApprovalRequired("command", "高危命令需要确认", risk)
        if self.is_command_allowlisted(command):
            return risk, shlex.split(command)
        if self.mode == "safe":
            reason = "安全执行模式要求确认此命令" if self.mode == "safe" else "高危命令需要确认"
            raise ApprovalRequired("command", reason, risk)
        return risk, shlex.split(command)

    def validate_read(self, relative_path: str, approved: bool = False) -> str:
        if type(approved) is not bool:
            raise PolicyError("approved must be a boolean")
        return self.resolve(relative_path)
