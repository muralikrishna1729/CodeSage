"""Tests for configurable AST-aware chunking (P1.1)."""

from tree_sitter import Parser

from app.ingestion.chunker import (
    PY_LANGUAGE,
    JS_LANGUAGE,
    JAVA_LANGUAGE,
    CodeChunk,
    chunk_file,
    extract_chunks,
    extract_imports,
    split_text_with_overlap,
)


def _parse_py(source: bytes):
    return Parser(PY_LANGUAGE).parse(source)


def _parse_js(source: bytes):
    return Parser(JS_LANGUAGE).parse(source)


def _parse_java(source: bytes):
    return Parser(JAVA_LANGUAGE).parse(source)


def fake_word_counter(text: str) -> int:
    """Deterministic token counter based on whitespace-delimited words."""
    if not text:
        return 0
    return len(text.split())


# 1. Small function remains one chunk
def test_small_function_remains_one_chunk():
    source = b"def small_func():\n    return 42\n"
    tree = _parse_py(source)
    chunks = extract_chunks(tree.root_node, source, "test.py", [], token_counter=fake_word_counter, target_tokens=100)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.function_name == "small_func"
    assert chunk.parent_symbol is None
    assert (chunk.start_line, chunk.end_line) == (1, 2)
    assert "return 42" in chunk.content


# 2. Small class remains one chunk
def test_small_class_remains_one_chunk():
    source = b'''class SmallClass:
    def method_one(self):
        return 1
'''
    tree = _parse_py(source)
    chunks = extract_chunks(tree.root_node, source, "test.py", [], token_counter=fake_word_counter, target_tokens=100)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.function_name == "SmallClass"
    assert chunk.parent_symbol is None
    assert (chunk.start_line, chunk.end_line) == (1, 3)


# 3. Normal-size methods are not separately indexed when complete class fits
def test_normal_size_methods_not_separately_indexed_when_class_fits():
    source = b'''class Foo:
    def bar(self):
        pass
    def baz(self):
        pass
'''
    tree = _parse_py(source)
    # Target tokens large enough to hold whole Foo
    chunks = extract_chunks(tree.root_node, source, "test.py", [], token_counter=fake_word_counter, target_tokens=50)

    assert len(chunks) == 1
    assert chunks[0].function_name == "Foo"
    assert chunks[0].parent_symbol is None
    # Verify methods are not separately present in chunk list
    func_names = [c.function_name for c in chunks]
    assert "Foo.bar" not in func_names
    assert "bar" not in func_names
    assert "Foo.baz" not in func_names


# 4. Oversized class becomes context and method chunks
def test_oversized_class_becomes_context_and_method_chunks():
    source = b'''class PaymentProcessor(BaseProcessor):
    """Handles payments and tax computations."""
    TAX_RATE = 0.05

    def calculate_tax(self, amount):
        if amount > 100:
            return amount * self.TAX_RATE
        return 0

    def refund(self, tx_id):
        status = "pending"
        return status
'''
    tree = _parse_py(source)
    # Total tokens is ~35. Set target_tokens=18 so class exceeds budget
    chunks = extract_chunks(
        tree.root_node, source, "pay.py", [],
        token_counter=fake_word_counter, target_tokens=18, overlap_tokens=3
    )

    # Must produce class context chunk + method chunks, not one oversized class chunk
    assert len(chunks) >= 3
    names = [c.function_name for c in chunks]
    assert "PaymentProcessor" in names
    assert "PaymentProcessor.calculate_tax" in names
    assert "PaymentProcessor.refund" in names

    # Class context chunk checks
    ctx_chunk = next(c for c in chunks if c.function_name == "PaymentProcessor")
    assert ctx_chunk.parent_symbol is None
    assert "class PaymentProcessor(BaseProcessor):" in ctx_chunk.content
    assert ctx_chunk.start_line == 1
    assert ctx_chunk.end_line <= 4


# 5. Fully qualified method names are correct
def test_fully_qualified_method_names():
    source = b'''class PaymentProcessor:
    def calculate_tax(self):
        """Tax calculation."""
        return 0
    def process_payment(self):
        """Process payment."""
        return True
'''
    tree = _parse_py(source)
    chunks = extract_chunks(
        tree.root_node, source, "pay.py", [],
        token_counter=fake_word_counter, target_tokens=8, overlap_tokens=2
    )

    method_chunks = [c for c in chunks if c.function_name != "PaymentProcessor"]
    assert len(method_chunks) == 2
    for mc in method_chunks:
        assert mc.parent_symbol == "PaymentProcessor"
        assert mc.function_name.startswith("PaymentProcessor.")
    assert {"PaymentProcessor.calculate_tax", "PaymentProcessor.process_payment"} == {
        c.function_name for c in method_chunks
    }


# 6. Oversized method splits at AST statement boundaries
def test_oversized_method_splits_at_ast_statement_boundaries():
    source = b'''def long_method():
    a = 1
    b = 2
    c = 3
    d = 4
    e = 5
    f = 6
    g = 7
    return a + b + c + d + e + f + g
'''
    tree = _parse_py(source)
    # Target tokens small enough that statements must be split across multiple chunks
    chunks = extract_chunks(
        tree.root_node, source, "m.py", [],
        token_counter=fake_word_counter, target_tokens=10, overlap_tokens=2
    )

    assert len(chunks) > 1
    for c in chunks:
        assert c.function_name == "long_method"
        assert fake_word_counter(c.content) <= 10
        # Line numbers must be within the method range
        assert 1 <= c.start_line <= 9
        assert 1 <= c.end_line <= 10

    # First chunk starts at first statement, subsequent chunks continue
    assert chunks[0].start_line == 2


# 7. Nested classes retain correct parent metadata
def test_nested_classes_retain_correct_parent_metadata():
    source = b'''class Outer:
    """Outer doc."""
    val = 1
    class Inner:
        """Inner doc."""
        def inner_method(self):
            return 42
'''
    tree = _parse_py(source)
    chunks = extract_chunks(
        tree.root_node, source, "nested.py", [],
        token_counter=fake_word_counter, target_tokens=12, overlap_tokens=2
    )

    inner_chunks = [c for c in chunks if "Inner" in c.function_name]
    assert len(inner_chunks) >= 1
    inner = inner_chunks[0]
    assert inner.parent_symbol == "Outer"
    assert inner.function_name.startswith("Outer.Inner")


# 8. Oversized Python lambda expressions are handled
def test_oversized_python_lambda_handled():
    words = "word " * 60
    source = f'long_lambda = lambda x: "{words}"\n'.encode("utf-8")
    tree = _parse_py(source)
    chunks = extract_chunks(
        tree.root_node, source, "lam.py", [],
        token_counter=fake_word_counter, target_tokens=20, overlap_tokens=4
    )

    assert len(chunks) > 1
    for c in chunks:
        assert c.function_name == "long_lambda"
        assert fake_word_counter(c.content) <= 20
        assert c.start_line == 1
        assert c.end_line == 1


# 9. JavaScript/TypeScript arrow functions are handled
def test_javascript_arrow_functions_handled():
    source = b'''class ApiHandler {
    handleRequest = (req) => {
        const a = req.body;
        const b = a.value;
        const c = b * 2;
        const d = c + 1;
        return d;
    };
}
'''
    tree = _parse_js(source)
    chunks = extract_chunks(
        tree.root_node, source, "api.js", [],
        token_counter=fake_word_counter, target_tokens=15, overlap_tokens=2
    )

    arrow_chunks = [c for c in chunks if "handleRequest" in c.function_name]
    assert len(arrow_chunks) >= 1
    for ac in arrow_chunks:
        assert ac.parent_symbol == "ApiHandler"
        assert ac.function_name == "ApiHandler.handleRequest"
        assert fake_word_counter(ac.content) <= 15


# 10. Java lambda expressions are handled
def test_java_lambda_expressions_handled():
    source = b'''class Service {
    void process() {
        Consumer<String> action = s -> {
            int x = 1;
            int y = 2;
            int z = x + y;
            System.out.println(z);
        };
    }
}
'''
    tree = _parse_java(source)
    chunks = extract_chunks(
        tree.root_node, source, "Service.java", [],
        token_counter=fake_word_counter, target_tokens=14, overlap_tokens=2
    )

    assert len(chunks) > 1
    for c in chunks:
        assert fake_word_counter(c.content) <= 14
        assert c.function_name.startswith("Service")


# 11. Token-counter injection works with a deterministic fake
def test_token_counter_injection_works_with_deterministic_fake():
    source = b'''def add(a, b):
    x = 1
    y = 2
    z = 3
    w = 4
    return a + b + x + y + z + w
'''
    tree = _parse_py(source)

    # Fake counter that counts characters divided by 5
    def char_counter(text: str) -> int:
        return max(1, len(text) // 5)

    chunks = extract_chunks(
        tree.root_node, source, "calc.py", [],
        token_counter=char_counter, target_tokens=8, overlap_tokens=2
    )

    assert len(chunks) > 1
    for c in chunks:
        assert char_counter(c.content) <= 8


# 12. Every final chunk stays within the token limit
def test_every_final_chunk_within_token_limit():
    source = b'''class HeavyProcessor(Base):
    """A heavy processor with many complex operations."""
    CONST_A = 100
    CONST_B = 200

    def compute(self, data):
        step1 = data * 2
        step2 = step1 + self.CONST_A
        step3 = step2 - self.CONST_B
        if step3 > 0:
            result = step3 * 10
            return result
        return 0

    def cleanup(self):
        finished = True
        return finished
'''
    tree = _parse_py(source)
    target_limit = 15
    chunks = extract_chunks(
        tree.root_node, source, "heavy.py", [],
        token_counter=fake_word_counter, target_tokens=target_limit, overlap_tokens=3
    )

    assert len(chunks) >= 3
    for c in chunks:
        token_count = fake_word_counter(c.content)
        assert token_count <= target_limit, f"Chunk {c.function_name} exceeded limit: {token_count} > {target_limit}"


# 13. Overlap is applied correctly during token-level fallback
def test_overlap_applied_during_token_fallback():
    long_statement = "val = " + " ".join([f"term{i}" for i in range(40)])
    source = long_statement.encode("utf-8")
    chunks = split_text_with_overlap(
        long_statement, 0, source, "stmt.py", "val", None, [], "",
        target_tokens=15, overlap_tokens=4, token_counter=fake_word_counter
    )

    assert len(chunks) >= 3
    # Check that adjacent chunks share overlapping words
    for i in range(len(chunks) - 1):
        words_curr = set(chunks[i].content.split())
        words_next = set(chunks[i + 1].content.split())
        shared = words_curr.intersection(words_next)
        assert len(shared) > 0, f"Expected overlap between chunk {i} and {i + 1}"


# 14. Original start/end line numbers are preserved
def test_original_start_end_lines_preserved():
    source = b'''# Line 1: Comment
# Line 2: Another comment
class Service:
    def action(self):
        return True
'''
    tree = _parse_py(source)
    chunks = extract_chunks(
        tree.root_node, source, "srv.py", [],
        token_counter=fake_word_counter, target_tokens=50
    )

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.start_line == 3
    assert chunk.end_line == 5
    lines = source.decode("utf-8").splitlines()
    assert lines[chunk.start_line - 1].startswith("class Service:")


# 15. A single exceptionally long source line is handled without violating token budget
def test_single_exceptionally_long_source_line():
    long_line = 'DATA = "' + ("x" * 2000) + '"\n'
    source = long_line.encode("utf-8")
    tree = _parse_py(source)

    def char_counter(text: str) -> int:
        return max(1, len(text) // 10)

    target_tokens = 50
    chunks = extract_chunks(
        tree.root_node, source, "long_line.py", [],
        token_counter=char_counter, target_tokens=target_tokens, overlap_tokens=5
    )

    assert len(chunks) > 1
    for c in chunks:
        assert char_counter(c.content) <= target_tokens
        assert c.start_line == 1
        assert c.end_line == 1


# 16. Existing unsupported-file fallback and import-extraction tests continue to pass
def test_extract_imports_python():
    source = b"import os\nfrom pathlib import Path\n\ndef foo():\n    pass\n"
    tree = _parse_py(source)
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
    assert chunks[0].function_name == "FILE"
    assert (chunks[0].start_line, chunks[0].end_line) == (1, 3)
    assert chunks[0].parent_symbol is None


# 17. Settings validation tests
def test_config_settings_validation():
    import pytest
    from app.config import Settings

    with pytest.raises(ValueError, match="chunk_target_tokens must be positive"):
        Settings(chunk_target_tokens=0)

    with pytest.raises(ValueError, match="chunk_overlap_tokens must be non-negative"):
        Settings(chunk_overlap_tokens=-1)

    with pytest.raises(ValueError, match="chunk_overlap_tokens must be smaller than chunk_target_tokens"):
        Settings(chunk_target_tokens=100, chunk_overlap_tokens=100)

    with pytest.raises(ValueError, match="context_max_tokens must be positive"):
        Settings(context_max_tokens=0)


# 18. Context budget integration tests
def test_context_budget_respects_settings_and_no_1500_char_truncation():
    from app.agent.context_budget import build_context_text

    long_content = "def sample():\n" + ("    x = 1\n" * 150)  # ~1600 characters
    kb_results = [
        {"file_path": "a.py", "start_line": 1, "end_line": 150, "content": long_content}
    ]
    # Default uses settings.context_max_tokens (4000)
    text = build_context_text(kb_results)
    # The full content must NOT be silently truncated at 1500 chars
    assert long_content in text


# 19. Qdrant store_chunks payload integration test
def test_store_chunks_includes_parent_symbol(monkeypatch):
    from unittest.mock import MagicMock
    from app.ingestion import embed_store

    mock_client = MagicMock()
    mock_client.collection_exists.return_value = True
    mock_dense_model = MagicMock()
    mock_dense_model.encode.return_value = MagicMock(tolist=lambda: [[0.1] * 768])
    mock_sparse_model = MagicMock()
    sparse_vec = MagicMock()
    sparse_vec.indices.tolist.return_value = [1, 2]
    sparse_vec.values.tolist.return_value = [0.5, 0.5]
    mock_sparse_model.embed.return_value = [sparse_vec]

    monkeypatch.setattr(embed_store, "client", mock_client)
    monkeypatch.setattr(embed_store, "get_model", lambda: mock_dense_model)
    monkeypatch.setattr(embed_store, "get_sparse_model", lambda: mock_sparse_model)

    chunk = CodeChunk(
        file_path="service.py",
        function_name="Service.process",
        start_line=10,
        end_line=20,
        content="def process(self): pass",
        parent_symbol="Service",
    )

    embed_store.store_chunks([chunk], repo_name="my-repo")

    upsert_calls = mock_client.upsert.call_args_list
    assert len(upsert_calls) == 1
    points = upsert_calls[0].kwargs["points"]
    assert len(points) == 1
    assert points[0].payload["parent_symbol"] == "Service"
    assert points[0].payload["function_name"] == "Service.process"


# 20. Qdrant search retrieval includes parent_symbol
def test_search_returns_parent_symbol(monkeypatch):
    from unittest.mock import MagicMock
    from app.ingestion import embed_store

    mock_client = MagicMock()
    mock_dense_model = MagicMock()
    mock_dense_model.encode.return_value = MagicMock(tolist=lambda: [0.1] * 768)
    mock_sparse_model = MagicMock()
    sparse_vec = MagicMock()
    sparse_vec.indices.tolist.return_value = [1, 2]
    sparse_vec.values.tolist.return_value = [0.5, 0.5]
    mock_sparse_model.embed.return_value = [sparse_vec]

    point = MagicMock()
    point.score = 0.95
    point.payload = {
        "file_path": "a.py",
        "function_name": "Class.method",
        "start_line": 1,
        "end_line": 5,
        "content": "code",
        "parent_symbol": "Class",
    }
    query_response = MagicMock()
    query_response.points = [point]
    mock_client.query_points.return_value = query_response

    monkeypatch.setattr(embed_store, "client", mock_client)
    monkeypatch.setattr(embed_store, "get_model", lambda: mock_dense_model)
    monkeypatch.setattr(embed_store, "get_sparse_model", lambda: mock_sparse_model)

    results = embed_store.search("test query", "my-repo")
    assert len(results) == 1
    assert results[0]["parent_symbol"] == "Class"
    assert results[0]["function_name"] == "Class.method"

