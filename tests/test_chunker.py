"""Regression tests for the chunker (see Plan/PHASE1_EXPLORATION.md, Stages 4-6)."""

from tree_sitter import Parser

from app.ingestion.chunker import (
    PY_LANGUAGE,
    CodeChunk,
    chunk_file,
    extract_chunks,
    extract_imports,
)


def _parse(source: bytes):
    parser = Parser(PY_LANGUAGE)
    return parser.parse(source)


def test_class_with_methods_yields_one_class_chunk():
    """The whole class is ONE chunk; methods inside must not be double-counted."""
    source = b'''
class Foo:
    def bar(self):
        pass
    def baz(self):
        pass
'''
    tree = _parse(source)
    chunks = extract_chunks(tree.root_node, source, "test.py", [])

    assert len(chunks) == 1  # only Foo — bar/baz are inside the captured class
    chunk = chunks[0]
    assert chunk.function_name == "Foo"
    assert (chunk.start_line, chunk.end_line) == (2, 6)  # 1-based, inclusive
    lines = source.decode().splitlines()
    assert lines[chunk.start_line - 1] == "class Foo:"


def test_top_level_function_chunk():
    source = b"def foo():\n    return 1\n"
    tree = _parse(source)
    chunks = extract_chunks(tree.root_node, source, "m.py", [])

    assert len(chunks) == 1
    assert chunks[0].function_name == "foo"
    assert (chunks[0].start_line, chunks[0].end_line) == (1, 2)


def test_extract_imports_python():
    source = b"import os\nfrom pathlib import Path\n\ndef foo():\n    pass\n"
    tree = _parse(source)
    assert extract_imports(tree.root_node, source, "python") == [
        "import os",
        "from pathlib import Path",
    ]


def test_chunk_file_non_code_falls_back_to_file_chunk(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("hello\nworld\n", encoding="utf-8")

    chunks = chunk_file(str(readme))
    assert len(chunks) == 1
    assert isinstance(chunks[0], CodeChunk)
    assert chunks[0].function_name == "FILE"  # whole-file fallback sentinel
    assert (chunks[0].start_line, chunks[0].end_line) == (1, 3)  # count("\n") + 1

