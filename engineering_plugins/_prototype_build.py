"""Self-contained trusted verifier, executed as python -c inside the workspace sandbox."""
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

SUFFIXES = {'.html', '.css', '.js', '.mjs', '.json', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico',
            '.woff', '.woff2', '.ttf', '.otf', '.mp4', '.webm', '.mp3', '.wav'}
LIBRARIES = {'vendor/codespider/' + name for name in ('vue.min.js', 'element-ui.js', 'element-ui.css',
             'fonts/element-icons.woff', 'fonts/element-icons.ttf', 'VUE-LICENSE', 'ELEMENT-UI-LICENSE')}
ROOT = Path.cwd().resolve()
MAX_BYTES = 64 * 1024 * 1024


def asset(reference, owner):
    reference = reference.strip()
    if not reference or reference.startswith(('#', 'data:', 'blob:')):
        return
    url = urlsplit(reference)
    if url.scheme or url.netloc or reference.startswith('/'):
        raise ValueError('%s 引用了外部或根目录资源 %s；请使用本地相对路径，Element UI 请引用 vendor/codespider/' % (owner, reference))
    path = Path(owner).parent / unquote(url.path)
    absolute = (ROOT / path).resolve()
    if absolute != ROOT and ROOT not in absolute.parents:
        raise ValueError('资源路径越过工程边界：' + reference)
    relative = absolute.relative_to(ROOT).as_posix()
    if relative not in FILES and relative not in LIBRARIES:
        raise ValueError('%s 引用了缺失或不可发布的资源：%s' % (owner, reference))
    return relative


def javascript(source, owner, module=False):
    result = subprocess.run(['node', '--input-type=' + ('module' if module else 'commonjs'), '--check'],
        input=source, text=True, capture_output=True, timeout=10)
    if result.returncode:
        raise ValueError('JavaScript 语法错误 %s：%s' % (owner, result.stderr[-1600:]))
    # Static module imports must resolve without npm or an import-map CDN.
    for match in re.finditer(r'''(?:\bfrom\s*|\bimport\s*\(?\s*)["']([^"']+)["']''', source):
        reference = match.group(1)
        if not reference.startswith(('./', '../')):
            raise ValueError('模块导入必须使用本地相对路径：' + reference)
        asset(reference, owner)


def css(source, owner):
    for match in re.finditer(r'''url\(\s*["']?([^\s)'";]+)|@import\s+["']([^"']+)''', source):
        asset(match.group(1) or match.group(2), owner)


class Page(HTMLParser):
    def __init__(self, owner):
        super().__init__(convert_charrefs=False)
        self.owner = owner
        self.script = None
        self.style = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag in ('iframe', 'base'):
            raise ValueError('隔离原型不支持 ' + tag + '，请使用本地页面和相对资源路径')
        if attrs.get('style'):
            css(attrs['style'], self.owner)
        if tag in ('script', 'img', 'source', 'video', 'audio') and attrs.get('src'):
            linked = asset(attrs['src'], self.owner)
            if tag == 'script' and linked and linked not in LIBRARIES:
                SCRIPT_TYPES[linked] = attrs.get('type') == 'module'
        if tag == 'link' and attrs.get('href'):
            asset(attrs['href'], self.owner)
        if attrs.get('poster'):
            asset(attrs['poster'], self.owner)
        if tag == 'script':
            kind = attrs.get('type', '')
            self.script = [kind == 'module', []] if not attrs.get('src') and kind in ('', 'module', 'text/javascript', 'application/javascript') else None
        if tag == 'style':
            self.style = []

    def handle_data(self, data):
        if self.script is not None: self.script[1].append(data)
        if self.style is not None: self.style.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            javascript(''.join(self.script[1]), self.owner + ' inline script', self.script[0]); self.script = None
        if tag == 'style' and self.style is not None:
            css(''.join(self.style), self.owner); self.style = None


def main():
    global FILES, SCRIPT_TYPES
    FILES, SCRIPT_TYPES = {}, {}
    total = 0
    for current, dirs, files in os.walk(ROOT, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'dist', 'build', 'tests', '__pycache__')]
        for name in dirs + files:
            if (Path(current) / name).is_symlink():
                raise ValueError('原型资源不能包含符号链接：' + name)
        for name in files:
            path = Path(current) / name
            relative = path.relative_to(ROOT).as_posix()
            if name.startswith('.') or (path.suffix.lower() not in SUFFIXES and relative not in LIBRARIES):
                continue
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError('原型资源必须是普通文件')
            with path.open('rb') as handle:
                content = handle.read(MAX_BYTES + 1)
            total += len(content)
            if len(FILES) >= 4000 or total > MAX_BYTES:
                raise ValueError('原型资源超过 64 MB / 4000 文件限制')
            FILES[relative] = content
    if 'index.html' not in FILES:
        raise ValueError('前端原型缺少 index.html')
    for name, content in FILES.items():
        if name.endswith('.html'):
            parser = Page(name); parser.feed(content.decode('utf-8')); parser.close()
            if parser.script is not None or parser.style is not None:
                raise ValueError('HTML 中有未闭合的 script/style：' + name)
    for name, content in FILES.items():
        if name in LIBRARIES:
            continue  # Bundled libraries are integrity-checked before build.
        if name.endswith(('.js', '.mjs')):
            javascript(content.decode('utf-8'), name, SCRIPT_TYPES.get(name, True))
        if name.endswith('.css'):
            css(content.decode('utf-8'), name)
    if len(sys.argv) > 1:
        output = ROOT / sys.argv[1]
        if output.parent != ROOT or not output.name.startswith('.codespider-preview-'):
            raise ValueError('无效的原型构建输出目录')
        output.mkdir()
        for name, content in FILES.items():
            target = output / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
    print('原型检查通过：%s 个静态资源，JavaScript 语法及本地资源引用有效。行为效果请在预览中验收。' % len(FILES))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr); sys.exit(1)
