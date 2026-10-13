import os
from typing import Any, Dict, List


def detect_project(root: str) -> Dict[str, Any]:
    files = set(os.listdir(root))
    if "pom.xml" in files or "build.gradle" in files or "build.gradle.kts" in files:
        return {"type": "java-springboot", "commands": ["mvn -q test", "mvn spring-boot:run"]}
    if "package.json" in files:
        package_path = os.path.join(root, "package.json")
        try:
            import json
            with open(package_path, "r", encoding="utf-8") as handle:
                package = json.load(handle)
            deps = dict(package.get("dependencies", {}), **package.get("devDependencies", {}))
            if "vue" in deps or any(name.endswith(".vue") for name in os.listdir(root)):
                install = "npm ci" if "package-lock.json" in files else "npm install"
                # An interrupted install can leave node_modules behind. Always
                # reconcile with the manifest/lock rather than trusting it.
                setup = [install + " --ignore-scripts --no-audit --no-fund"]
                return {"type": "vue", "commands": ["npm run build", "npm run dev"], "setup_commands": setup,
                        "verification_commands": ["npm test -- --run"] if package.get("scripts", {}).get("test") else []}
        except (OSError, ValueError):
            pass
    python_markers = {"pyproject.toml", "requirements.txt", "setup.py", "manage.py"}
    source_files = _project_files(root)
    if files.intersection(python_markers) or any(name.endswith(".py") for name in source_files):
        tests_dir = os.path.isdir(os.path.join(root, "tests"))
        has_tests = tests_dir or any(name.startswith("test") and name.endswith(".py") for name in source_files)
        tests = ["python3 -m unittest discover -s tests -v" if tests_dir else "python3 -m unittest discover -v"] if has_tests else []
        return {"type": "python", "commands": ["python3 -m compileall -q .", "pytest"], "verification_commands": tests}
    return {"type": "unknown", "commands": []}


def _project_files(root: str):
    """Return bounded, ignored-directory-aware file names for type detection."""
    result = []
    ignored = {".git", ".codespider", "node_modules", "target", "dist", "__pycache__", ".venv", "venv"}
    for current, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in ignored and not name.startswith(".")]
        result.extend(names)
        if len(result) >= 10000:
            break
    return result[:10000]
