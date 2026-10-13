"""Deployable Streamlit viewer for the AI Architect interview notebooks.

Run locally with:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import base64
import html
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import streamlit as st


APP_ROOT = Path(__file__).resolve().parent
NOTEBOOK_GLOB = "*.ipynb"
IGNORED_PARTS = {".git", ".venv", ".ipynb_checkpoints", "node_modules"}


st.set_page_config(
    page_title="AI Architect Interview Series",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
    :root { --brand: #7c3aed; --brand-2: #2563eb; }
    .stApp { background: #f8fafc; }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #111827 0%, #172554 100%);
    }
    [data-testid="stSidebar"] * { color: #f8fafc; }
    [data-testid="stSidebar"] div[role="radiogroup"] label {
        border-radius: 10px;
        padding: .35rem .5rem;
    }
    [data-testid="stSidebar"] div[role="radiogroup"] label:hover {
        background: rgba(255,255,255,.09);
    }
    .hero {
        padding: 1.4rem 1.6rem;
        border: 1px solid #ddd6fe;
        border-radius: 18px;
        color: #111827;
        background: linear-gradient(120deg, #ede9fe 0%, #eff6ff 55%, #ecfeff 100%);
        box-shadow: 0 10px 30px rgba(30, 41, 59, .08);
        margin-bottom: 1rem;
    }
    .hero h1 { margin: 0 0 .35rem; font-size: 2rem; }
    .hero p { margin: 0; color: #475569; }
    .notebook-meta {
        display: inline-block;
        margin: 0 .4rem .5rem 0;
        padding: .25rem .65rem;
        border-radius: 999px;
        background: #eef2ff;
        color: #3730a3;
        font-size: .82rem;
        font-weight: 650;
    }
    [data-testid="stMarkdownContainer"] mjx-container[display="true"],
    [data-testid="stMarkdownContainer"] .katex-display {
        padding: .9rem 1rem;
        overflow-x: auto;
        border-left: 4px solid var(--brand-2);
        border-radius: 9px;
        background: linear-gradient(90deg, rgba(37,99,235,.07), rgba(124,58,237,.035));
    }
    div[data-testid="stExpander"] {
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        background: #fff;
    }
    .cell-divider { border-top: 1px solid #e5e7eb; margin: 1.25rem 0; }
    </style>
    """,
    unsafe_allow_html=True,
)


def pretty_name(value: str) -> str:
    """Turn a folder or filename into a readable navigation label."""
    value = re.sub(r"^\d+[._ -]*", "", value)
    value = re.sub(r"(?:_Interview)?_Handbook$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"_\d+plus$", "", value, flags=re.IGNORECASE)
    value = value.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", value).strip().title()


def discover_notebooks() -> dict[str, list[Path]]:
    """Discover repository notebooks and group them by top-level subject."""
    grouped: dict[str, list[Path]] = defaultdict(list)
    for path in APP_ROOT.rglob(NOTEBOOK_GLOB):
        relative = path.relative_to(APP_ROOT)
        if any(part in IGNORED_PARTS or part.startswith(".") for part in relative.parts):
            continue
        subject = pretty_name(relative.parts[0]) if len(relative.parts) > 1 else "General"
        grouped[subject].append(path)
    return {
        subject: sorted(paths, key=lambda item: str(item.relative_to(APP_ROOT)).lower())
        for subject, paths in sorted(grouped.items())
    }


@st.cache_data(show_spinner=False)
def load_notebook(path_string: str, modified_ns: int) -> dict[str, Any]:
    """Load notebook JSON; modified_ns invalidates the cache after edits."""
    del modified_ns
    return json.loads(Path(path_string).read_text(encoding="utf-8"))


def notebook_title(notebook: dict[str, Any], fallback: str) -> str:
    """Use the first Markdown H1 as the display title when available."""
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "markdown":
            continue
        source = "".join(cell.get("source", []))
        match = re.search(r"^#\s+(.+?)\s*$", source, flags=re.MULTILINE)
        if match:
            return re.sub(r"<[^>]+>", "", match.group(1)).strip()
    return pretty_name(fallback)


def data_uri(mime_type: str, payload: str) -> str:
    return f"data:{mime_type};base64,{payload.replace(chr(10), '')}"


def rewrite_markdown_images(
    markdown: str, attachments: dict[str, Any], notebook_dir: Path
) -> str:
    """Embed notebook attachments and safe local images for hosted rendering."""
    for name, bundle in attachments.items():
        if not isinstance(bundle, dict):
            continue
        for mime_type, payload in bundle.items():
            if mime_type.startswith("image/") and isinstance(payload, str):
                markdown = markdown.replace(f"attachment:{name}", data_uri(mime_type, payload))
                break

    image_pattern = re.compile(r"(!\[[^\]]*\]\()([^\s)]+)([^)]*\))")

    def replace_local_image(match: re.Match[str]) -> str:
        prefix, target, suffix = match.groups()
        if target.startswith(("http://", "https://", "data:", "attachment:")):
            return match.group(0)
        candidate = (notebook_dir / target).resolve()
        try:
            candidate.relative_to(APP_ROOT)
        except ValueError:
            return match.group(0)
        if not candidate.is_file():
            return match.group(0)
        mime_by_suffix = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".webp": "image/webp",
        }
        mime_type = mime_by_suffix.get(candidate.suffix.lower())
        if not mime_type:
            return match.group(0)
        payload = base64.b64encode(candidate.read_bytes()).decode("ascii")
        return f"{prefix}{data_uri(mime_type, payload)}{suffix}"

    return image_pattern.sub(replace_local_image, markdown)


def render_output(output: dict[str, Any], key: str) -> None:
    """Render a saved Jupyter output without executing notebook code."""
    output_type = output.get("output_type", "")
    if output_type == "stream":
        text = "".join(output.get("text", []))
        if text.strip():
            st.code(text.rstrip(), language="text")
        return

    if output_type == "error":
        traceback_text = "\n".join(output.get("traceback", []))
        st.error(f"{output.get('ename', 'Notebook error')}: {output.get('evalue', '')}")
        if traceback_text:
            st.code(traceback_text, language="text")
        return

    data = output.get("data", {})
    if not isinstance(data, dict):
        return

    if "image/png" in data:
        payload = "".join(data["image/png"]) if isinstance(data["image/png"], list) else data["image/png"]
        st.image(base64.b64decode(payload))
        return
    if "image/jpeg" in data:
        payload = "".join(data["image/jpeg"]) if isinstance(data["image/jpeg"], list) else data["image/jpeg"]
        st.image(base64.b64decode(payload))
        return
    if "image/svg+xml" in data:
        svg = "".join(data["image/svg+xml"]) if isinstance(data["image/svg+xml"], list) else data["image/svg+xml"]
        st.iframe(svg, height=520, alt="Saved SVG notebook output")
        return
    if "text/html" in data:
        html_output = "".join(data["text/html"]) if isinstance(data["text/html"], list) else data["text/html"]
        st.iframe(html_output, height=460, alt="Saved HTML notebook output")
        return
    if "application/json" in data:
        st.json(data["application/json"])
        return
    if "text/plain" in data:
        plain = "".join(data["text/plain"]) if isinstance(data["text/plain"], list) else data["text/plain"]
        if plain.strip():
            st.code(plain.rstrip(), language="text")


def render_notebook(
    notebook: dict[str, Any], notebook_path: Path, show_code: bool, show_outputs: bool
) -> None:
    cells = notebook.get("cells", [])
    for index, cell in enumerate(cells):
        cell_type = cell.get("cell_type")
        source = "".join(cell.get("source", []))

        if cell_type == "markdown":
            rendered = rewrite_markdown_images(
                source, cell.get("attachments", {}), notebook_path.parent
            )
            st.markdown(rendered, unsafe_allow_html=True)
        elif cell_type == "code":
            outputs = cell.get("outputs", [])
            if show_code and source.strip():
                label = f"Code cell {index + 1}"
                with st.expander(label, expanded=False):
                    st.code(source, language="python", line_numbers=True)
            if show_outputs:
                for output_index, output in enumerate(outputs):
                    render_output(output, f"{index}-{output_index}")
        elif cell_type == "raw" and source.strip():
            st.code(source, language="text")


notebooks_by_subject = discover_notebooks()
if not notebooks_by_subject:
    st.error("No notebook files were found in this repository.")
    st.stop()

with st.sidebar:
    st.markdown("# 🧠 Interview Series")
    st.caption("Choose a subject and notebook")
    subject_names = list(notebooks_by_subject)
    selected_subject = st.radio("Subjects", subject_names, label_visibility="collapsed")

    subject_notebooks = notebooks_by_subject[selected_subject]
    notebook_labels = {
        pretty_name(path.stem): path for path in subject_notebooks
    }
    st.markdown("---")
    selected_label = st.radio(
        "Notebooks", list(notebook_labels), label_visibility="collapsed"
    )
    selected_path = notebook_labels[selected_label]

    st.markdown("---")
    show_code = st.checkbox("Show code cells", value=False)
    show_outputs = st.checkbox("Show saved outputs", value=True)
    st.caption(f"{sum(len(items) for items in notebooks_by_subject.values())} notebooks available")

try:
    notebook = load_notebook(str(selected_path), selected_path.stat().st_mtime_ns)
except (OSError, json.JSONDecodeError) as exc:
    st.error(f"Unable to open this notebook: {exc}")
    st.stop()

title = notebook_title(notebook, selected_path.stem)
relative_path = selected_path.relative_to(APP_ROOT)
code_cells = sum(cell.get("cell_type") == "code" for cell in notebook.get("cells", []))
markdown_cells = sum(cell.get("cell_type") == "markdown" for cell in notebook.get("cells", []))

st.markdown(
    f"""
    <section class="hero">
      <h1>{html.escape(title)}</h1>
      <p>{html.escape(selected_subject)} · Interactive notebook reader</p>
    </section>
    <span class="notebook-meta">📖 {markdown_cells} reading cells</span>
    <span class="notebook-meta">💻 {code_cells} code cells</span>
    <span class="notebook-meta">📁 {html.escape(str(relative_path.parent))}</span>
    """,
    unsafe_allow_html=True,
)

with selected_path.open("rb") as notebook_file:
    st.download_button(
        "Download notebook",
        data=notebook_file.read(),
        file_name=selected_path.name,
        mime="application/x-ipynb+json",
        use_container_width=False,
    )

st.markdown('<div class="cell-divider"></div>', unsafe_allow_html=True)
render_notebook(notebook, selected_path, show_code, show_outputs)

st.markdown('<div class="cell-divider"></div>', unsafe_allow_html=True)
st.caption("AI Architect Interview Series · Notebook content is rendered from saved files; code is not executed by the app.")
