"""Reject implementation imports outside composition (AST incl. relative imports).

Core/ORM/schema imports are shared. Business code consumes contracts. A service
may import same-domain implementations; composition alone assembles domains.
Dynamic imports are forbidden in business code to prevent bypasses.
"""
import argparse, ast, importlib.util
from pathlib import Path

DOMAINS = {
    "identity_service": "identity", "access_service": "identity", "binding_service": "identity", "profile_service": "identity", "change_service": "identity", "media_service": "identity",
    "health_service": "health", "medication_service": "health", "notification_service": "health", "report_service": "health",
    "agent_service": "agent", "memory_service": "agent",
}
def domain_of(path: Path) -> str | None:
    stem = path.stem
    return DOMAINS.get(stem, stem.removesuffix('_flows') if stem.removesuffix('_flows') in {'identity','health','agent'} else None)
def violations(root: Path) -> list[str]:
    errors = []
    for path in sorted(root.rglob('*.py')):
        rel = path.relative_to(root)
        if rel.parts[0] not in {'services','application','routers'}:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        owner = domain_of(path)
        package = 'app.' + '.'.join(rel.parts[:-1])
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if node.level:
                    module = importlib.util.resolve_name('.'*node.level + module, package)
                targets = [module] + [module + '.' + a.name for a in node.names]
            elif isinstance(node, ast.Call) and ((isinstance(node.func, ast.Name) and node.func.id == '__import__') or (isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module')):
                errors.append(f'{rel}:{node.lineno}: dynamic import forbidden')
            for target in targets:
                if target == 'app.composition' or target.startswith('app.composition.'):
                    errors.append(f'{rel}:{node.lineno}: business code cannot import composition')
                if target == 'app.services' or target.startswith('app.services.'):
                    name = target.split('.')[2] if len(target.split('.')) > 2 else None
                    target_domain = DOMAINS.get(name)
                    # Routers/flows cannot import concrete implementations, even same domain.
                    if rel.parts[0] != 'services' or owner is None or target_domain != owner:
                        errors.append(f'{rel}:{node.lineno}: implementation import {target}')
                        break
    return errors
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = violations(args.root)
    if errors:
        raise SystemExit('\n'.join(errors))
    print('Architecture OK: no cross-domain implementation imports')
if __name__ == '__main__':
    main()
