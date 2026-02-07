import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python tools/inspect_png_meta.py <path-to-png>")
        return 2

    p = Path(sys.argv[1]).expanduser().resolve()
    if not p.exists():
        print(f"file not found: {p}")
        return 1

    try:
        from PIL import Image  # type: ignore
    except Exception as e:
        print(f"PIL import error: {e}")
        return 1

    print(f"file: {p}")
    img = Image.open(p)
    try:
        print(f"format: {img.format}")
        info_keys = sorted(list(getattr(img, "info", {}).keys()))
        print(f"info keys ({len(info_keys)}): {info_keys}")

        text = getattr(img, "text", None)
        if text is None:
            print("img.text: <none>")
        else:
            try:
                text_keys = sorted(list(text.keys()))
                print(f"text keys ({len(text_keys)}): {text_keys}")
            except Exception:
                print(f"img.text: <non-dict> ({type(text).__name__})")

        for k in ["workflow", "prompt", "parameters", "Workflow", "Prompt"]:
            if text is not None and hasattr(text, "get"):
                v = text.get(k)
                if v is not None:
                    s = v if isinstance(v, str) else str(v)
                    print(f"text[{k}] type={type(v).__name__} len={len(s)}")

            v2 = getattr(img, "info", {}).get(k)
            if v2 is not None:
                s2 = v2 if isinstance(v2, str) else str(v2)
                print(f"info[{k}] type={type(v2).__name__} len={len(s2)}")
    finally:
        try:
            img.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())







