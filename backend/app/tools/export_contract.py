import argparse, hashlib, json
from pathlib import Path
from app.main import create_app

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "openapi.json"
def export_bytes() -> bytes:
    return (json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
def check_contract(path: Path) -> bool:
    return path.is_file() and path.read_bytes() == export_bytes()
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--path', type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    data = export_bytes()
    if args.check:
        if not check_contract(args.path):
            raise SystemExit("CONTRACT_DIFF: run export without --check and review the diff")
        print("OpenAPI matches " + hashlib.sha256(data).hexdigest())
    else:
        args.path.parent.mkdir(parents=True, exist_ok=True)
        args.path.write_bytes(data)
        print("Exported " + str(args.path) + " SHA256=" + hashlib.sha256(data).hexdigest())
if __name__ == '__main__':
    main()
