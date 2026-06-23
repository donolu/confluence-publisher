import pytest
from confluence_publisher.converter import (
    ConversionError,
    ConversionResult,
    ConfluenceRenderer,
    build_banner,
    content_hash,
    convert,
    _resolve_path,
)
import mistletoe
from mistletoe import Document


def render(md: str, source: str = "test.md", page_id_map: dict | None = None) -> str:
    with ConfluenceRenderer(source_path=source, page_id_map=page_id_map) as r:
        return r.render(Document(md))


# --- Headings ---

def test_heading_h1():
    assert render("# Hello") == "<h1>Hello</h1>"

def test_heading_h3():
    assert render("### Third") == "<h3>Third</h3>"

def test_heading_h6():
    assert render("###### Six") == "<h6>Six</h6>"


# --- Inline formatting ---

def test_bold():
    assert "<strong>bold</strong>" in render("**bold** text")

def test_italic():
    assert "<em>italic</em>" in render("_italic_ text")

def test_inline_code():
    assert "<code>x = 1</code>" in render("`x = 1`")

def test_inline_code_escapes_html():
    assert "<code>&lt;tag&gt;</code>" in render("`<tag>`")


# --- Paragraphs ---

def test_paragraph():
    assert render("Hello world") == "<p>Hello world</p>"

def test_html_escaped_in_text():
    assert render("a & b") == "<p>a &amp; b</p>"
    assert render("a < b") == "<p>a &lt; b</p>"


# --- Code blocks ---

def test_fenced_code_with_language():
    out = render("```python\nprint(1)\n```")
    assert 'ac:name="code"' in out
    assert 'ac:name="language">python' in out
    assert "<![CDATA[print(1)\n]]>" in out

def test_fenced_code_no_language():
    out = render("```\nsome code\n```")
    assert 'ac:name="code"' in out
    assert 'ac:name="language"' not in out
    assert "<![CDATA[some code\n]]>" in out

def test_mermaid_raises():
    with pytest.raises(ConversionError, match="Mermaid"):
        render("```mermaid\ngraph TD\n```")


# --- Lists ---

def test_unordered_list():
    out = render("- alpha\n- beta\n")
    assert out.startswith("<ul>")
    assert "<li>" in out
    assert "alpha" in out

def test_ordered_list():
    out = render("1. first\n2. second\n")
    assert out.startswith("<ol>")
    assert "first" in out

def test_nested_list():
    out = render("- parent\n  - child\n")
    assert out.count("<ul>") == 2


# --- Blockquote ---

def test_blockquote():
    out = render("> some quote\n")
    assert "<blockquote>" in out
    assert "some quote" in out


# --- Links ---

def test_external_link():
    out = render("[click here](https://example.com)")
    assert '<a href="https://example.com">click here</a>' in out

def test_link_href_escaping():
    out = render('[x](https://example.com/a&b"c)')
    assert "&amp;" in out
    assert "&quot;" in out

def test_internal_link_known():
    pid_map = {"docs/other.md": "42"}
    out = render("[see other](other.md)", source="docs/index.md", page_id_map=pid_map)
    assert 'ri:content-id="42"' in out
    assert "<ac:link>" in out
    assert "see other" in out

def test_internal_link_unknown_falls_back_to_plain():
    out = render("[see other](other.md)", source="docs/index.md", page_id_map={})
    assert '<a href="other.md">' in out
    assert "<ac:link>" not in out

def test_internal_link_with_path_traversal():
    pid_map = {"docs/arch.md": "99"}
    out = render("[arch](../docs/arch.md)", source="notes/index.md", page_id_map=pid_map)
    assert 'ri:content-id="99"' in out


# --- Images ---

def test_image_external_renders():
    out = render("![alt text](https://example.com/img.png)")
    assert "<ac:image" in out
    assert '<ri:url ri:value="https://example.com/img.png"/>' in out
    assert 'ac:alt="alt text"' in out

def test_image_local_renders_as_attachment():
    out = render("![diagram](images/fig.png)", source="docs/arch.md")
    assert "<ac:image" in out
    assert '<ri:attachment ri:filename="fig.png"/>' in out

def test_image_local_collected():
    with ConfluenceRenderer(source_path="docs/arch.md") as r:
        r.render(Document("![a](images/fig.png)\n![b](images/other.png)\n"))
        assert r.images == ["docs/images/fig.png", "docs/images/other.png"]

def test_image_no_alt():
    out = render("![](images/fig.png)", source="docs/arch.md")
    assert "<ac:image>" in out or "<ac:image " not in out or 'ac:alt=""' not in out


# --- Thematic break ---

def test_thematic_break():
    out = render("---\n")
    assert "<hr/>" in out


# --- Line breaks ---

def test_hard_line_break():
    out = render("line one  \nline two\n")
    assert "<br/>" in out

def test_soft_line_break_is_space():
    out = render("line one\nline two\n")
    assert "<br/>" not in out
    assert "line one" in out
    assert "line two" in out


# --- Unsupported nodes raise ConversionError ---

def test_table_renders():
    body = render("| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert "<table>" in body
    assert "<th>" in body
    assert "<td>" in body

def test_strikethrough_raises():
    with pytest.raises(ConversionError, match="Strikethrough"):
        render("~~deleted~~")


# --- Banner ---

def test_build_banner_contains_source():
    banner = build_banner("docs/arch.md", "abc1234")
    assert 'ac:name="info"' in banner
    assert "docs/arch.md" in banner
    assert "abc1234" in banner

def test_build_banner_escapes_path():
    banner = build_banner("docs/<special>.md", "sha")
    assert "&lt;special&gt;" in banner


# --- convert() ---

def test_convert_returns_result():
    result = convert("# Hello\n", "test.md", "abc1234")
    assert isinstance(result, ConversionResult)
    assert "<h1>Hello</h1>" in result.body
    assert "<h1>Hello</h1>" in result.full_body
    assert 'ac:name="info"' in result.full_body
    assert "abc1234" in result.full_body
    assert 'ac:name="info"' not in result.body

def test_convert_banner_prepended():
    result = convert("para\n", "f.md", "sha")
    assert result.full_body.startswith('<ac:structured-macro ac:name="info">')
    assert result.full_body.endswith("<p>para</p>")

def test_convert_collects_images():
    result = convert("![fig](images/fig.png)\n", "docs/arch.md", "sha")
    assert result.images == ["docs/images/fig.png"]

def test_convert_no_images_on_external():
    result = convert("![fig](https://example.com/fig.png)\n", "docs/arch.md", "sha")
    assert result.images == []

def test_convert_internal_links_resolved():
    result = convert(
        "[see arch](arch.md)\n",
        "docs/index.md",
        "sha",
        page_id_map={"docs/arch.md": "42"},
    )
    assert 'ri:content-id="42"' in result.body


# --- _resolve_path ---

def test_resolve_path_simple():
    assert _resolve_path("docs", "arch.md") == "docs/arch.md"

def test_resolve_path_traversal():
    assert _resolve_path("docs/adr", "../arch.md") == "docs/arch.md"

def test_resolve_path_root_file():
    assert _resolve_path("", "README.md") == "README.md"

def test_resolve_path_nested():
    assert _resolve_path("docs", "images/fig.png") == "docs/images/fig.png"


# --- content_hash ---

def test_content_hash_deterministic():
    assert content_hash("hello") == content_hash("hello")

def test_content_hash_differs():
    assert content_hash("hello") != content_hash("world")


# --- Full sample doc ---

def test_sample_fixture(tmp_path):
    sample = (
        "# Title\n\nParagraph with **bold** and _italic_.\n\n"
        "```python\nx = 1\n```\n\n"
        "[link](https://example.com)\n\n"
        "> quote\n\n---\n"
    )
    result = convert(sample, "sample.md", "deadbeef")
    assert "<h1>Title</h1>" in result.body
    assert "<strong>bold</strong>" in result.body
    assert "<em>italic</em>" in result.body
    assert 'ac:name="code"' in result.body
    assert "<blockquote>" in result.body
    assert "<hr/>" in result.body
    assert "deadbeef" in result.full_body
