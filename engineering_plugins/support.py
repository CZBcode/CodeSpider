import os

def project_files(root):
    result = []
    ignored = {'.git', '.codespider', 'node_modules', 'target', 'dist', '__pycache__', '.venv', 'venv'}
    for current, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in ignored and not name.startswith('.') and not os.path.islink(os.path.join(current, name))]
        result.extend(names)
        if len(result) >= 10000:
            break
    return result[:10000]
