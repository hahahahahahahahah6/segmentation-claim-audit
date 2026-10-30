"""Offline documentation and AST inspection. Source is never executed."""
import argparse
import ast
import fnmatch
import json
import os
from pathlib import Path
import re
import sys

from . import __version__
from .phrases import SEGMENTATION, NOSEGMENTATION


def normalize(text):
    return re.sub(r'\s+', ' ', text.lower().replace("n't", ' not').replace('-', ' ')).strip()


def _pattern(phrases):
    return re.compile(r'\b(?:' + '|'.join(re.escape(p) for p in sorted(phrases, key=len, reverse=True)) + r')\b')


def claims(text):
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            lines.append('')
        elif match:
            fence = match[1]
            lines.append('')
        else:
            lines.append(line)
    positive = negative = False
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        paragraph = normalize(paragraph)
        neg = _pattern(NOSEGMENTATION)
        negative |= bool(neg.search(paragraph))
        positive |= bool(_pattern(SEGMENTATION).search(neg.sub(' ', paragraph)))
    return positive, negative


def evidence(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    aliases = {}
    shadow = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadow.add(node.name)
        elif isinstance(node, ast.arg):
            shadow.add(node.arg)
        elif isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for item in node.names:
                aliases[item.asname or item.name] = node.module + '.' + item.name
    bindings = {}

    def key(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = key(node.value)
            return base + '.' + node.attr if base else None
        return None

    def resolve(node):
        name = key(node)
        if not name or name.split('.')[0] in shadow:
            return ''
        head, *tail = name.split('.')
        return '.'.join([aliases.get(head, ''), *tail]) if head in aliases else ''

    def construction(node):
        if not isinstance(node, ast.Call):
            return None
        path = resolve(node.func)
        if not path.startswith('mediapipe.'):
            return None
        if path.endswith('.selfie_segmentation.SelfieSegmentation'):
            return 'selfie'
        if path.endswith(('.ImageSegmenter', '.ImageSegmenter.create_from_options')):
            return 'tasks'
        return None

    # Fixed point supports attribute, annotated, with-target and alias bindings.
    for _ in range(len(list(ast.walk(tree))) + 1):
        changed = False
        for node in ast.walk(tree):
            pairs = []
            if isinstance(node, ast.Assign):
                pairs = [(target, node.value) for target in node.targets]
            elif isinstance(node, ast.AnnAssign) and node.value:
                pairs = [(node.target, node.value)]
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                pairs = [(item.optional_vars, item.context_expr) for item in node.items if item.optional_vars]
            for target, value in pairs:
                kind = construction(value) or bindings.get(key(value))
                target_key = key(target)
                if kind and target_key and bindings.get(target_key) != kind:
                    bindings[target_key] = kind
                    changed = True
        if not changed:
            break
    for node in ast.walk(tree):
        if construction(node):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            kind = construction(node.func.value) or bindings.get(key(node.func.value))
            if kind and node.func.attr in (('segment',) if kind == 'selfie' else ('segment', 'segment_for_video', 'segment_async')):
                return True
    return False


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir() or not os.access(root, os.R_OK | os.X_OK) or not root.stat().st_mode & 0o444:
        raise ValueError('invalid or unreadable root')
    positive = negative = production = tests = False
    count = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
        for filename in sorted(files):
            path = Path(directory) / filename
            rel = path.relative_to(root)
            if path.is_symlink() or any(fnmatch.fnmatchcase(rel.as_posix(), glob) for glob in ignore):
                continue
            doc = rel.as_posix() == 'README.md' or (path.suffix == '.md' and 'docs' in rel.parts[:-1])
            source = path.suffix == '.py'
            if not (doc or source):
                continue
            try:
                text = path.read_text(encoding='utf-8')
            except (OSError, UnicodeError) as exc:
                raise ValueError('unreadable input: ' + rel.as_posix()) from exc
            count += 1
            if doc:
                pos, neg = claims(text)
                positive |= pos
                negative |= neg
            if source and not set(rel.parts[:-1]) & {'fixtures', 'docs', 'examples'}:
                is_test = 'tests' in rel.parts[:-1] or filename.startswith('test_') or filename.endswith('_test.py')
                if evidence(text):
                    if is_test:
                        tests = True
                    else:
                        production = True
    findings = []
    if positive and not production:
        findings.append(dict(rule='documented-segmentation-claim-false', severity='MEDIUM' if tests else 'HIGH', message='Documented capability has no production source evidence.'))
    if negative and production:
        findings.append(dict(rule='documented-no-segmentation-claim-false', severity='HIGH', message='Documented absence conflicts with production source evidence.'))
    return dict(verdict='FAIL' if findings else 'PASS', findings=findings, files_scanned=count)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=('HIGH', 'MEDIUM'), default='HIGH')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.ignore)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result))
    else:
        print(result['verdict'])
        for finding in result['findings']:
            print('{severity} {rule}: {message}'.format(**finding))
        if args.verbose:
            print('Files scanned: ' + str(result['files_scanned']))
    return 2 if any(f['severity'] == 'HIGH' or args.fail_on == 'MEDIUM' for f in result['findings']) else 0
