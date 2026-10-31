import json
import sys

from app.reports import MAX_UPLOAD, extract_fields


def main():
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    data = sys.stdin.buffer.read(MAX_UPLOAD + 1)
    try:
        result = extract_fields("report.pdf", data, sys.argv[1])
        sys.stdout.write(json.dumps({"result": result}))
    except (ValueError, KeyError) as exc:
        sys.stdout.write(json.dumps({"error": str(exc)}))


if __name__ == "__main__":
    main()
