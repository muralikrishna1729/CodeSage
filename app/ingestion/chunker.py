import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable
from tree_sitter import Parser, Language, Node
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjs
import tree_sitter_java as tsjava

# Ensure project root is on sys.path
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
from app.config import settings

PY_LANGUAGE = Language(tspython.language())
JS_LANGUAGE = Language(tsjs.language())
JAVA_LANGUAGE = Language(tsjava.language())

CLASS_NODE_TYPES = {
    "class_definition",                               # python
    "class_declaration", "class",                     # js/ts
    "interface_declaration",                          # java
    "enum_declaration", "record_declaration",
}

FUNCTION_NODE_TYPES = {
    "function_definition",                            # python
    "function_declaration", "method_definition",      # js/ts
    "generator_function_declaration", "function",
    "method_declaration", "constructor_declaration",  # java
}

LAMBDA_NODE_TYPES = {
    "lambda",             # python
    "arrow_function",     # js/ts
    "lambda_expression",  # java
}

IMPORT_NODE_TYPES = {
    "python": {"import_statement", "import_from_statement"},
    "javascript": {"import_statement"},
    "java": {"import_declaration"},
}

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

TokenCounter = Callable[[str], int]


def default_token_counter(text: str) -> int:
    """Lightweight standard token estimation (~4 chars/token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


@dataclass
class CodeChunk:
    file_path: str
    function_name: str
    start_line: int
    end_line: int
    content: str
    imports: list[str] = field(default_factory=list)
    parent_symbol: str | None = None


def _get_parser_and_lang(file_path: str) -> tuple[Parser, str] | tuple[None, None]:
    parser = Parser()
    if file_path.endswith(".py"):
        parser.language = PY_LANGUAGE
        return parser, "python"
    if file_path.endswith((".js", ".ts", ".jsx", ".tsx")):
        parser.language = JS_LANGUAGE
        return parser, "javascript"
    if file_path.endswith(".java"):
        parser.language = JAVA_LANGUAGE
        return parser, "java"
    return None, None


def extract_imports(root_node, source: bytes, lang: str) -> list[str]:
    """Collect import statements via ITERATIVE preorder DFS."""
    imports = []
    target_types = IMPORT_NODE_TYPES.get(lang, set())
    stack = [root_node]
    while stack:
        node = stack.pop()
        if node.type in target_types:
            import_text = source[node.start_byte:node.end_byte].decode(errors="ignore").strip()
            imports.append(import_text)
        stack.extend(reversed(node.children))
    return imports


def _get_node_name(node: Node, source: bytes) -> str:
    """Extract symbol name from AST node, parent declarator, or line-based label."""
    # 1. Direct identifier child
    for c in node.children:
        if c.type in ("identifier", "property_identifier", "type_identifier", "constructor"):
            return source[c.start_byte:c.end_byte].decode("utf-8", errors="ignore").strip()

    # 2. Enclosing assignment / declaration for lambdas
    parent = node.parent
    if parent:
        if parent.type in (
            "assignment", "variable_declarator", "pair",
            "field_definition", "public_field_definition", "field_declaration"
        ):
            for c in parent.children:
                if c.type in ("identifier", "property_identifier"):
                    return source[c.start_byte:c.end_byte].decode("utf-8", errors="ignore").strip()
                if c.type == "variable_declarator":
                    for sub in c.children:
                        if sub.type in ("identifier", "property_identifier"):
                            return source[sub.start_byte:sub.end_byte].decode("utf-8", errors="ignore").strip()

    # 3. Stable symbol label using line number when unnamed
    line = node.start_point.row + 1
    if node.type in ("lambda", "lambda_expression"):
        return f"<lambda@L{line}>"
    if node.type == "arrow_function":
        return f"<arrow@L{line}>"
    return f"<anonymous@L{line}>"


def _find_lambda_in_node(node: Node) -> Node | None:
    """Find any lambda expression within a variable/field assignment statement."""
    if node.type in LAMBDA_NODE_TYPES:
        return node
    for child in node.children:
        if child.type in LAMBDA_NODE_TYPES:
            return child
        for sub in child.children:
            if sub.type in LAMBDA_NODE_TYPES:
                return sub
            for subsub in sub.children:
                if subsub.type in LAMBDA_NODE_TYPES:
                    return subsub
    return None


def _fully_qualified_name(name: str, parent_symbol: str | None) -> str:
    if parent_symbol:
        return f"{parent_symbol}.{name}"
    return name


def _get_body_node(node: Node) -> Node | None:
    body = node.child_by_field_name("body")
    if body:
        return body
    for c in node.children:
        if c.type in ("block", "statement_block", "class_body", "constructor_body", "interface_body"):
            return c
    return None


def _extract_class_prefix(class_node: Node, source: bytes) -> str:
    """Extract class declaration line and docstring context (if present)."""
    body = _get_body_node(class_node)
    end_hdr = body.start_byte if body else class_node.end_byte
    hdr = source[class_node.start_byte:end_hdr].decode("utf-8", errors="ignore").strip()

    docstring = ""
    if body:
        # Check first statement in body for docstring
        for c in body.children:
            if c.type == "expression_statement":
                for sub in c.children:
                    if sub.type == "string":
                        docstring = source[c.start_byte:c.end_byte].decode("utf-8", errors="ignore").strip()
                        break
                break
            elif c.type not in ("{", "}", ";", "comment"):
                break

    if docstring:
        return f"{hdr}\n    {docstring}"
    return hdr


def _extract_func_header(func_node: Node, source: bytes) -> str:
    body = _get_body_node(func_node)
    if body:
        hdr = source[func_node.start_byte:body.start_byte].decode("utf-8", errors="ignore").strip()
    else:
        hdr = source[func_node.start_byte:func_node.end_byte].decode("utf-8", errors="ignore").strip().split("\n")[0]
    return hdr


def split_text_with_overlap(
    text: str,
    base_start_byte: int,
    source: bytes,
    file_path: str,
    function_name: str,
    parent_symbol: str | None,
    imports: list[str],
    prefix: str,
    target_tokens: int,
    overlap_tokens: int,
    token_counter: TokenCounter,
) -> list[CodeChunk]:
    """Token-offset-based splitting for atomic leaf AST units or long lines."""
    chunks = []
    # Make sure prefix leaves room for content
    active_prefix = prefix
    if active_prefix and token_counter(active_prefix) >= target_tokens - 10:
        first_line = active_prefix.split("\n")[0]
        if token_counter(first_line) < target_tokens - 10:
            active_prefix = first_line
        else:
            active_prefix = ""

    curr = 0
    n = len(text)
    while curr < n:
        low = curr + 1
        high = n
        best = low

        while low <= high:
            mid = (low + high) // 2
            slice_text = text[curr:mid]
            cand = f"{active_prefix}\n{slice_text}" if active_prefix else slice_text
            if token_counter(cand) <= target_tokens:
                best = mid
                low = mid + 1
            else:
                high = mid - 1

        end_pos = best
        if end_pos < n:
            space_pos = text.rfind(" ", curr, end_pos)
            nl_pos = text.rfind("\n", curr, end_pos)
            break_pos = max(space_pos, nl_pos)
            if break_pos > curr and break_pos >= curr + int((end_pos - curr) * 0.7):
                end_pos = break_pos + 1

        slice_text = text[curr:end_pos]
        final_content = f"{active_prefix}\n{slice_text}" if active_prefix else slice_text

        slice_start_byte = base_start_byte + len(text[:curr].encode("utf-8"))
        slice_end_byte = base_start_byte + len(text[:end_pos].encode("utf-8"))
        start_line = source[:slice_start_byte].count(b"\n") + 1
        end_ref = slice_end_byte - 1 if (slice_end_byte > slice_start_byte and source[slice_end_byte - 1:slice_end_byte] == b"\n") else slice_end_byte
        end_line = source[:end_ref].count(b"\n") + 1

        chunks.append(
            CodeChunk(
                file_path=file_path,
                function_name=function_name,
                start_line=start_line,
                end_line=end_line,
                content=final_content,
                imports=imports,
                parent_symbol=parent_symbol,
            )
        )

        if end_pos >= n:
            break

        # Calculate overlap starting point
        rev_low = curr + 1
        rev_high = end_pos
        best_overlap_start = end_pos
        while rev_low <= rev_high:
            mid = (rev_low + rev_high) // 2
            if token_counter(text[mid:end_pos]) <= overlap_tokens:
                best_overlap_start = mid
                rev_high = mid - 1
            else:
                rev_low = mid + 1

        next_curr = max(curr + 1, best_overlap_start)
        # Prefer breaking at line or space if available
        if next_curr < end_pos:
            nl = text.find("\n", next_curr, end_pos)
            sp = text.find(" ", next_curr, end_pos)
            cand_break = -1
            if nl != -1 and sp != -1:
                cand_break = min(nl, sp)
            elif nl != -1:
                cand_break = nl
            elif sp != -1:
                cand_break = sp
            if cand_break != -1 and cand_break > curr:
                next_curr = cand_break + 1

        curr = next_curr

    return chunks


def _split_statements(
    statements: list[Node],
    source: bytes,
    file_path: str,
    function_name: str,
    parent_symbol: str | None,
    imports: list[str],
    sig_prefix: str,
    target_tokens: int,
    overlap_tokens: int,
    token_counter: TokenCounter,
) -> list[CodeChunk]:
    """Split a list of AST statements at statement boundaries."""
    chunks = []
    current_batch: list[Node] = []

    def flush_batch():
        nonlocal current_batch
        if not current_batch:
            return
        first = current_batch[0]
        last = current_batch[-1]
        batch_text = source[first.start_byte:last.end_byte].decode("utf-8", errors="ignore").strip()
        content = f"{sig_prefix}\n{batch_text}" if sig_prefix else batch_text
        start_line = first.start_point.row + 1
        end_line = last.end_point.row + 1
        chunks.append(
            CodeChunk(
                file_path=file_path,
                function_name=function_name,
                start_line=start_line,
                end_line=end_line,
                content=content,
                imports=imports,
                parent_symbol=parent_symbol,
            )
        )
        current_batch = []

    for stmt in statements:
        stmt_text = source[stmt.start_byte:stmt.end_byte].decode("utf-8", errors="ignore").strip()
        cand = f"{sig_prefix}\n{stmt_text}" if sig_prefix else stmt_text

        if token_counter(cand) > target_tokens:
            # Current statement alone exceeds the target
            flush_batch()

            # Check if this compound statement has an inner block we can divide
            nested_body = None
            for c in stmt.children:
                if c.type in ("block", "statement_block"):
                    nested_body = c
                    break

            if nested_body:
                hdr_end = nested_body.start_byte
                stmt_hdr = source[stmt.start_byte:hdr_end].decode("utf-8", errors="ignore").strip()
                nested_prefix = f"{sig_prefix}\n    {stmt_hdr}" if sig_prefix else stmt_hdr
                if token_counter(nested_prefix) >= target_tokens - 10:
                    nested_prefix = stmt_hdr

                inner_stmts = [c for c in nested_body.children if c.type not in ("{", "}", ";")]
                if inner_stmts:
                    chunks.extend(
                        _split_statements(
                            inner_stmts,
                            source,
                            file_path,
                            function_name,
                            parent_symbol,
                            imports,
                            nested_prefix,
                            target_tokens,
                            overlap_tokens,
                            token_counter,
                        )
                    )
                else:
                    chunks.extend(
                        split_text_with_overlap(
                            stmt_text,
                            stmt.start_byte,
                            source,
                            file_path,
                            function_name,
                            parent_symbol,
                            imports,
                            sig_prefix,
                            target_tokens,
                            overlap_tokens,
                            token_counter,
                        )
                    )
            else:
                # Atomic statement exceeding budget: fallback to token-level splitting with overlap
                chunks.extend(
                    split_text_with_overlap(
                        stmt_text,
                        stmt.start_byte,
                        source,
                        file_path,
                        function_name,
                        parent_symbol,
                        imports,
                        sig_prefix,
                        target_tokens,
                        overlap_tokens,
                        token_counter,
                    )
                )
        else:
            if not current_batch:
                current_batch.append(stmt)
            else:
                batch_start = current_batch[0].start_byte
                batch_end = stmt.end_byte
                cand_text = source[batch_start:batch_end].decode("utf-8", errors="ignore").strip()
                combined = f"{sig_prefix}\n{cand_text}" if sig_prefix else cand_text
                if token_counter(combined) <= target_tokens:
                    current_batch.append(stmt)
                else:
                    flush_batch()
                    current_batch.append(stmt)

    flush_batch()
    return chunks


def _split_oversized_function(
    func_node: Node,
    source: bytes,
    file_path: str,
    function_name: str,
    parent_symbol: str | None,
    imports: list[str],
    class_prefix: str | None,
    target_tokens: int,
    overlap_tokens: int,
    token_counter: TokenCounter,
) -> list[CodeChunk]:
    """Split an oversized function or method into statement-level fragments."""
    body = _get_body_node(func_node)
    hdr = _extract_func_header(func_node, source)

    if class_prefix:
        short_class = class_prefix.split("\n")[0]
        sig_prefix = f"{short_class}\n    {hdr}"
    else:
        sig_prefix = hdr

    if token_counter(sig_prefix) >= target_tokens - 10:
        sig_prefix = hdr
    if token_counter(sig_prefix) >= target_tokens - 10:
        sig_prefix = ""

    if not body:
        raw_content = source[func_node.start_byte:func_node.end_byte].decode("utf-8", errors="ignore").strip()
        return split_text_with_overlap(
            raw_content,
            func_node.start_byte,
            source,
            file_path,
            function_name,
            parent_symbol,
            imports,
            sig_prefix,
            target_tokens,
            overlap_tokens,
            token_counter,
        )

    stmts = [c for c in body.children if c.type not in ("{", "}", ";")]
    if not stmts:
        raw_content = source[func_node.start_byte:func_node.end_byte].decode("utf-8", errors="ignore").strip()
        return split_text_with_overlap(
            raw_content,
            func_node.start_byte,
            source,
            file_path,
            function_name,
            parent_symbol,
            imports,
            sig_prefix,
            target_tokens,
            overlap_tokens,
            token_counter,
        )

    return _split_statements(
        stmts,
        source,
        file_path,
        function_name,
        parent_symbol,
        imports,
        sig_prefix,
        target_tokens,
        overlap_tokens,
        token_counter,
    )


def extract_chunks(
    root_node,
    source: bytes,
    file_path: str,
    imports: list[str],
    token_counter: TokenCounter | None = None,
    target_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[CodeChunk]:
    """Collect function/class chunks via iterative AST traversal with AST-aware splitting."""
    if token_counter is None:
        token_counter = default_token_counter
    if target_tokens is None:
        target_tokens = settings.chunk_target_tokens
    if overlap_tokens is None:
        overlap_tokens = settings.chunk_overlap_tokens

    chunks: list[CodeChunk] = []

    # Stack holds tuples: (node, parent_symbol, class_prefix)
    stack: list[tuple[Node, str | None, str | None]] = [
        (c, None, None) for c in reversed(root_node.children)
    ]

    while stack:
        node, parent_sym, class_pref = stack.pop()

        # 1. CLASS NODES
        if node.type in CLASS_NODE_TYPES:
            raw_content = source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
            name = _get_node_name(node, source)
            fq_name = _fully_qualified_name(name, parent_sym)

            if token_counter(raw_content) <= target_tokens:
                # Normal-sized class: emit whole class as 1 chunk and DO NOT descend
                start_line = node.start_point.row + 1
                end_line = node.end_point.row + 1
                chunks.append(
                    CodeChunk(
                        file_path=file_path,
                        function_name=fq_name,
                        start_line=start_line,
                        end_line=end_line,
                        content=raw_content,
                        imports=imports,
                        parent_symbol=parent_sym,
                    )
                )
                continue

            # Oversized class: do NOT emit whole class. Split into context + members.
            body = _get_body_node(node)
            class_pref = _extract_class_prefix(node, source)

            if not body:
                chunks.extend(
                    split_text_with_overlap(
                        raw_content,
                        node.start_byte,
                        source,
                        file_path,
                        fq_name,
                        parent_sym,
                        imports,
                        "",
                        target_tokens,
                        overlap_tokens,
                        token_counter,
                    )
                )
                continue

            # Find context nodes (before first method/member) and member nodes
            body_children = [c for c in body.children if c.type not in ("{", "}", ";")]
            first_member_idx = -1
            for idx, c in enumerate(body_children):
                if c.type in CLASS_NODE_TYPES or c.type in FUNCTION_NODE_TYPES or _find_lambda_in_node(c) is not None:
                    first_member_idx = idx
                    break

            # Class context chunk
            if first_member_idx == -1:
                ctx_end_byte = node.end_byte
            elif first_member_idx == 0:
                ctx_end_byte = body.start_byte
            else:
                ctx_end_byte = body_children[first_member_idx - 1].end_byte

            ctx_text = source[node.start_byte:ctx_end_byte].decode("utf-8", errors="ignore").strip()
            if ctx_text:
                ctx_start_line = node.start_point.row + 1
                ctx_end_line = source[:ctx_end_byte].count(b"\n") + 1
                if token_counter(ctx_text) <= target_tokens:
                    chunks.append(
                        CodeChunk(
                            file_path=file_path,
                            function_name=fq_name,
                            start_line=ctx_start_line,
                            end_line=ctx_end_line,
                            content=ctx_text,
                            imports=imports,
                            parent_symbol=parent_sym,
                        )
                    )
                else:
                    chunks.extend(
                        split_text_with_overlap(
                            ctx_text,
                            node.start_byte,
                            source,
                            file_path,
                            fq_name,
                            parent_sym,
                            imports,
                            "",
                            target_tokens,
                            overlap_tokens,
                            token_counter,
                        )
                    )

            # Push member children in reversed order
            members = body_children if first_member_idx == -1 else body_children[first_member_idx:]
            for m in reversed(members):
                stack.append((m, fq_name, class_pref))
            continue

        # 2. FUNCTION / METHOD NODES
        if node.type in FUNCTION_NODE_TYPES:
            raw_content = source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
            name = _get_node_name(node, source)
            fq_name = _fully_qualified_name(name, parent_sym)
            start_line = node.start_point.row + 1
            end_line = node.end_point.row + 1

            if class_pref:
                cand_full = f"{class_pref}\n\n{raw_content}"
                cand_short = f"{class_pref.split(chr(10))[0]}\n\n{raw_content}"

                if token_counter(cand_full) <= target_tokens:
                    chunks.append(
                        CodeChunk(
                            file_path=file_path,
                            function_name=fq_name,
                            start_line=start_line,
                            end_line=end_line,
                            content=cand_full,
                            imports=imports,
                            parent_symbol=parent_sym,
                        )
                    )
                    continue
                elif token_counter(cand_short) <= target_tokens:
                    chunks.append(
                        CodeChunk(
                            file_path=file_path,
                            function_name=fq_name,
                            start_line=start_line,
                            end_line=end_line,
                            content=cand_short,
                            imports=imports,
                            parent_symbol=parent_sym,
                        )
                    )
                    continue
                elif token_counter(raw_content) <= target_tokens:
                    chunks.append(
                        CodeChunk(
                            file_path=file_path,
                            function_name=fq_name,
                            start_line=start_line,
                            end_line=end_line,
                            content=raw_content,
                            imports=imports,
                            parent_symbol=parent_sym,
                        )
                    )
                    continue
            else:
                if token_counter(raw_content) <= target_tokens:
                    chunks.append(
                        CodeChunk(
                            file_path=file_path,
                            function_name=fq_name,
                            start_line=start_line,
                            end_line=end_line,
                            content=raw_content,
                            imports=imports,
                            parent_symbol=parent_sym,
                        )
                    )
                    continue

            # Oversized function/method: split at statement boundaries
            chunks.extend(
                _split_oversized_function(
                    node,
                    source,
                    file_path,
                    fq_name,
                    parent_sym,
                    imports,
                    class_pref,
                    target_tokens,
                    overlap_tokens,
                    token_counter,
                )
            )
            continue

        # 3. LAMBDA / ARROW FUNCTION NODES
        lambda_node = _find_lambda_in_node(node)
        if lambda_node is not None and node.type not in CLASS_NODE_TYPES and node.type not in FUNCTION_NODE_TYPES:
            # If the current node contains a lambda (or is a lambda)
            target_node = lambda_node if node.type not in LAMBDA_NODE_TYPES else node
            raw_content = source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
            name = _get_node_name(target_node, source)
            fq_name = _fully_qualified_name(name, parent_sym)
            start_line = node.start_point.row + 1
            end_line = node.end_point.row + 1

            if token_counter(raw_content) <= target_tokens:
                chunks.append(
                    CodeChunk(
                        file_path=file_path,
                        function_name=fq_name,
                        start_line=start_line,
                        end_line=end_line,
                        content=raw_content,
                        imports=imports,
                        parent_symbol=parent_sym,
                    )
                )
                continue

            # Oversized lambda: check if it has a block body (e.g. JS arrow / Java lambda)
            body = _get_body_node(target_node)
            if body and body.children:
                stmts = [c for c in body.children if c.type not in ("{", "}", ";")]
                hdr = _extract_func_header(target_node, source)
                chunks.extend(
                    _split_statements(
                        stmts,
                        source,
                        file_path,
                        fq_name,
                        parent_sym,
                        imports,
                        hdr,
                        target_tokens,
                        overlap_tokens,
                        token_counter,
                    )
                )
            else:
                chunks.extend(
                    split_text_with_overlap(
                        raw_content,
                        node.start_byte,
                        source,
                        file_path,
                        fq_name,
                        parent_sym,
                        imports,
                        "",
                        target_tokens,
                        overlap_tokens,
                        token_counter,
                    )
                )
            continue

        # Non-symbol node: push children
        stack.extend((c, parent_sym, class_pref) for c in reversed(node.children))

    if not chunks:
        text = source.decode("utf-8", errors="ignore")
        if token_counter(text) <= target_tokens:
            return [CodeChunk(file_path, "FILE", 1, text.count("\n") + 1, text, imports, parent_symbol=None)]
        return split_text_with_overlap(
            text,
            0,
            source,
            file_path,
            "FILE",
            None,
            imports,
            "",
            target_tokens,
            overlap_tokens,
            token_counter,
        )

    return chunks


def chunk_file(
    file_path: str,
    token_counter: TokenCounter | None = None,
    target_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[CodeChunk]:
    if token_counter is None:
        token_counter = default_token_counter
    if target_tokens is None:
        target_tokens = settings.chunk_target_tokens
    if overlap_tokens is None:
        overlap_tokens = settings.chunk_overlap_tokens

    parser, lang = _get_parser_and_lang(file_path)
    source = Path(file_path).read_bytes()

    if parser is None:
        text = source.decode("utf-8", errors="ignore")
        if token_counter(text) <= target_tokens:
            return [CodeChunk(file_path, "FILE", 1, text.count("\n") + 1, text, parent_symbol=None)]
        return split_text_with_overlap(
            text,
            0,
            source,
            file_path,
            "FILE",
            None,
            [],
            "",
            target_tokens,
            overlap_tokens,
            token_counter,
        )

    tree = parser.parse(source)
    imports = extract_imports(tree.root_node, source, lang)
    chunks = extract_chunks(
        tree.root_node,
        source,
        file_path,
        imports,
        token_counter=token_counter,
        target_tokens=target_tokens,
        overlap_tokens=overlap_tokens,
    )

    if not chunks:
        text = source.decode("utf-8", errors="ignore")
        if token_counter(text) <= target_tokens:
            return [CodeChunk(file_path, "FILE", 1, text.count("\n") + 1, text, imports, parent_symbol=None)]
        return split_text_with_overlap(
            text,
            0,
            source,
            file_path,
            "FILE",
            None,
            imports,
            "",
            target_tokens,
            overlap_tokens,
            token_counter,
        )

    return chunks


def chunk_repo(
    repo_path: str,
    token_counter: TokenCounter | None = None,
    target_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[CodeChunk]:
    all_chunks = []
    for path in Path(repo_path).rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.suffix in (".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".md"):
            try:
                all_chunks.extend(
                    chunk_file(
                        str(path),
                        token_counter=token_counter,
                        target_tokens=target_tokens,
                        overlap_tokens=overlap_tokens,
                    )
                )
            except Exception as e:
                print(f"Error processing {path}: {e}")
    return all_chunks
