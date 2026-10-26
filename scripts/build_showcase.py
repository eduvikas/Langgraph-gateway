"""Inline showcase/run-data.json into showcase/template.html -> showcase/ai-gateway-showcase.html (one self-contained file)."""
import json
from pathlib import Path

S = Path(__file__).resolve().parent.parent / "showcase"


def build(data_path=S / "run-data.json", out_path=S / "ai-gateway-showcase.html"):
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    blob = json.dumps(data, separators=(",", ":"), default=str).replace("</", "<\\/")
    html = (S / "template.html").read_text(encoding="utf-8")
    assert "__DATA__" in html
    Path(out_path).write_text(html.replace("__DATA__", blob), encoding="utf-8")
    return Path(out_path)


if __name__ == "__main__":
    print("wrote", build(), f"({build().stat().st_size // 1024} KB)")
