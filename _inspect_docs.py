"""Inspect headings/styles in all Company_Documents."""
from docx import Document as DocxDocument
from pathlib import Path

docs_dir = Path("Company_Documents")
for f in sorted(docs_dir.glob("*.docx")):
    doc = DocxDocument(str(f))
    print("\n" + "=" * 90)
    print(f"FILE: {f.name}")
    print("=" * 90)
    for i, para in enumerate(doc.paragraphs[:50]):
        text = para.text.strip()
        if not text:
            continue
        style = para.style.name if para.style else "None"
        is_bold = any(run.bold for run in para.runs if run.bold is not None)
        font_sizes = set()
        for run in para.runs:
            if run.font and run.font.size:
                font_sizes.add(run.font.size.pt)
        size_str = str(font_sizes) if font_sizes else "default"
        marker = " <<<HEADING?" if (style.startswith("Heading") or style == "Title" or is_bold or text.isupper() or text.endswith(":")) else ""
        print(f"  [{i:3d}] style={style:25s} bold={str(is_bold):5s} sizes={size_str:15s} | {text[:85]}{marker}")
