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
                return {"type": "vue", "commands": ["npm run build", "npm run dev"]}
        except (OSError, ValueError):
            pass
    python_markers = {"pyproject.toml", "requirements.txt", "setup.py", "manage.py"}
    if files.intersection(python_markers) or any(name.endswith(".py") for name in files):
        return {"type": "python", "commands": ["python3 -m compileall -q .", "pytest"]}
    return {"type": "unknown", "commands": []}

