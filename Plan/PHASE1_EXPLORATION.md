# Phase 1 — Exploration Guide (chunker.py → repo_map.py → embed_store.py)

> Each stage: an explanation of *why* this piece exists and how the logic
> works, then a code snippet, then a test with expected output so you can
> tell working from broken. Run every checkpoint yourself before moving on.

---

# PART A — `app/ingestion/chunker.py`

## Stage 0 — The problem

Fixed-size chunking (say, every 500 characters) cuts through the middle of
functions with no regard for meaning. tree-sitter parses source code into an
**AST (Abstract Syntax Tree)** — a tree where each node represents a
structural piece of the code (a function, a class, an if-statement, an
import). Walking that tree and cutting chunks at function/class boundaries
means every chunk is a complete, self-contained unit of meaning.

## Stage 1 — Data shape

A plain container for one chunk's data.

```python
from dataclasses import dataclass, field

@dataclass
class CodeChunk:
    file_path: str
    function_name: str
    start_line: int
    end_line: int
    content: str
    imports: list[str] = field(default_factory=list)
```

**Why these fields:** `file_path` + `start_line`/`end_line` are what let you
later cite "see `auth.py:42`." `content` is the raw code text that gets
embedded. `imports` stays empty until Stage 6 — it lets `repo_map.py` build
a dependency graph later without re-parsing every file.

## Stage 2 — Pick a parser per file

tree-sitter needs a specific grammar (`Language`) per programming language,
attached to a `Parser`. Given a file, the first decision is which grammar
applies — based on extension.

```python
from tree_sitter import Parser, Language
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjs

PY_LANGUAGE = Language(tspython.language())
JS_LANGUAGE = Language(tsjs.language())

def get_parser_and_lang(file_path: str):
    parser = Parser()
    if file_path.endswith(".py"):
        parser.language = PY_LANGUAGE
        return parser, "python"
    if file_path.endswith((".js", ".ts", ".jsx", ".tsx")):
        parser.language = JS_LANGUAGE
        return parser, "javascript"
    return None, None
```

Returning `(None, None)` for anything else (README, JSON) is the signal the
rest of the pipeline uses to say "treat as plain text instead."

**Test:**
```python
p, lang = get_parser_and_lang("some_file.py")
print(lang)
```
**Expected output:** `python`

## Stage 3 — Look at the raw tree before extracting anything

tree-sitter's node type names shouldn't be guessed — print the real tree and
read them off directly.

```python
from pathlib import Path

source = Path("some_file.py").read_bytes()
parser, lang = get_parser_and_lang("some_file.py")
tree = parser.parse(source)

def walk(node, depth=0):
    print("  " * depth + node.type)
    for child in node.children:
        walk(child, depth + 1)

walk(tree.root_node)
```

**Expected output** (file with `def foo(x): return x`):
```
module
  function_definition
    def
    identifier
    parameters
      (
      identifier
      )
    :
    block
      return_statement
        return
        identifier
```

**How to read this:** each line = one AST node, indented by depth. The root
`module` node is the whole file. `function_definition` is what you match on
in Stage 4. Notice `identifier` appears twice — once as the function's name,
once as an argument name inside `parameters` — this ambiguity is why Stage 5
needs to be careful about *which* identifier child it grabs.

## Stage 4 — Extract chunks, don't double-count nested nodes

**The logic:** walk the tree recursively. At each node, check if its type is
one we care about (function/class). If yes, capture it as a chunk **and stop
recursing into its children** — a class node's children include its
methods, which are themselves function/method nodes. Without stopping,
you'd capture the whole class AND each method inside it separately —
duplicate chunks. The `return` right after appending is what prevents that.

If the node isn't a function/class, don't capture anything — just keep
walking its children, since the function you want might be nested deeper.

```python
FUNCTION_NODE_TYPES = {
    "function_definition", "class_definition",
    "function_declaration", "method_definition",
}

def extract_chunks(root_node, source: bytes, file_path: str, imports: list[str]):
    chunks = []

    def walk(node):
        if node.type in FUNCTION_NODE_TYPES:
            name_node = next(
                (c for c in node.children if c.type in ("identifier", "property_identifier")),
                None,
            )
            name = name_node.text.decode() if name_node else "anonymous"
            content = source[node.start_byte:node.end_byte].decode(errors="ignore")
            chunks.append(CodeChunk(
                file_path=file_path,
                function_name=name,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                content=content,
                imports=imports,
            ))
            return  # stop here — do NOT walk into this node's children
        for child in node.children:
            walk(child)

    walk(root_node)
    return chunks
```

Two details worth understanding:
- `source[node.start_byte:node.end_byte]` — every node knows its exact
  byte-offset span in the file. Slicing raw bytes by those offsets gives the
  exact original text, formatting included.
- `node.start_point[0] + 1` — tree-sitter counts lines from 0 internally;
  citations should count from 1, hence `+1`.

**Test on a class with 2 methods:**
```python
test_source = b'''
class Foo:
    def bar(self):
        pass
    def baz(self):
        pass
'''
tree = parser.parse(test_source)
chunks = extract_chunks(tree.root_node, test_source, "test.py", [])
for c in chunks:
    print(c.function_name, c.start_line, c.end_line)
```

**Expected output (correct):**
```
Foo 2 6
```
One chunk, the whole class. **If you instead see `Foo`, `bar`, AND `baz` as
three separate chunks**, a child slipped past the `return` — check whether
the `return` is really inside the `if` branch, not accidentally outside it.

## Stage 5 — Non-code files (README, config)

`chunk_file` is the front door: given any file path, decide whether to
AST-parse it or fall back to one whole-file plain-text chunk. That fallback
covers two cases: the file isn't code at all (README), or it's code with
zero functions/classes in it (a flat script) — either way, one chunk beats
returning nothing.

```python
def chunk_file(file_path: str) -> list[CodeChunk]:
    parser, lang = get_parser_and_lang(file_path)
    source = Path(file_path).read_bytes()

    if parser is None:
        text = source.decode("utf-8", errors="ignore")
        return [CodeChunk(file_path, "FILE", 1, text.count("\n") + 1, text)]

    tree = parser.parse(source)
    imports = extract_imports(tree.root_node, source, lang)  # Stage 6
    chunks = extract_chunks(tree.root_node, source, file_path, imports)

    if not chunks:
        text = source.decode("utf-8", errors="ignore")
        chunks = [CodeChunk(file_path, "FILE", 1, text.count("\n") + 1, text, imports)]

    return chunks
```

`function_name="FILE"` is a sentinel value marking "whole-file fallback, not
a real function" — used later (Stage 8) to filter real chunks from fallback.

**Test on a README.md:**
```python
chunks = chunk_file("README.md")
print(chunks[0].function_name, chunks[0].start_line, chunks[0].end_line)
```
**Expected output:** `FILE 1 <total line count of the README>`

## Stage 6 — Imports

`repo_map.py` later wants a dependency graph (which file imports which) to
trace "how does the auth flow work" across files. Same tree-walk pattern as
before, but it collects *every* import node found anywhere in the file,
without stopping after a match.

```python
IMPORT_NODE_TYPES = {
    "python": {"import_statement", "import_from_statement"},
    "javascript": {"import_statement"},
}

def extract_imports(root_node, source: bytes, language: str) -> list[str]:
    imports = []
    target_types = IMPORT_NODE_TYPES.get(language, set())

    def walk(node):
        if node.type in target_types:
            imports.append(source[node.start_byte:node.end_byte].decode(errors="ignore").strip())
        for child in node.children:
            walk(child)

    walk(root_node)
    return imports
```

This walk does **not** `return` after a match, unlike Stage 4 — imports
don't nest inside each other the way classes/methods do, so there's no
duplication risk to guard against.

**Test:**
```python
test_source = b"import os\nfrom pathlib import Path\n\ndef foo():\n    pass\n"
tree = parser.parse(test_source)
print(extract_imports(tree.root_node, test_source, "python"))
```
**Expected output:** `['import os', 'from pathlib import Path']`

## Stage 7 — Whole-repo walk

Pure filesystem traversal: walk every file, skip noise directories
(`.git`, `node_modules`, virtual envs), only process known extensions.

```python
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

def chunk_repo(repo_path: str) -> list[CodeChunk]:
    all_chunks = []
    for path in Path(repo_path).rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.suffix in (".py", ".js", ".ts", ".jsx", ".tsx", ".md"):
            try:
                all_chunks.extend(chunk_file(str(path)))
            except Exception as e:
                print(f"[chunker] Skipped {path}: {e}")
    return all_chunks
```

The `try/except` per file is deliberate: one malformed file shouldn't crash
ingestion for the whole repo — skip it, warn, keep going.

## Stage 8 — Full end-to-end test on your cloned repo

```python
from app.ingestion.chunker import chunk_repo

chunks = chunk_repo("repos/ai-engineering-interview-questions")
print(f"Total chunks: {len(chunks)}")
for c in chunks[:5]:
    print(f"{c.function_name:20} {c.file_path:50} lines {c.start_line}-{c.end_line}")
```

**What to expect from THIS repo:** it's mostly interview-question Markdown,
not source code — so most chunks should be `FILE` fallbacks, not real
function names. That's correct for this repo's content, not a bug — it just
means Stage 4's AST-extraction path barely gets exercised. To actually prove
that logic, test against a code-heavy repo too:

```python
chunks2 = chunk_repo("repos/fastapi")  # clone separately if needed
python_chunks = [c for c in chunks2 if c.function_name != "FILE"]
print(len(python_chunks), "real function/class chunks found")
print(python_chunks[0].content[:200])
```

**Sanity check:** open the actual source file at the printed line range and
confirm the function really starts/ends there. Off-by-one is almost always
a missing `+ 1` on `start_point[0]`.

---

# PART B — `app/ingestion/repo_map.py`

## Stage 0 — Why this file is separate from chunker.py

`chunker.py` gives *pieces* of code — good for "what does `validate_token()`
do." Not enough for "how does the login flow work end-to-end" — that needs
the **shape of the whole project**: folder layout, import graph, and
whatever the README already explains (often the single highest-value source
for architecture questions, since a human already wrote the summary).

## Stage 1 — Directory tree as text

Recursively walk the directory, building an indented text list — folders
get a name plus indented contents, files just get listed. This mirrors a
`tree`-command-style format LLMs already understand well.

```python
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

def build_directory_tree(repo_path: str, max_depth: int = 4) -> str:
    lines = []
    root = Path(repo_path)

    def walk(path: Path, prefix: str = "", depth: int = 0):
        if depth > max_depth:
            return
        entries = sorted(
            [p for p in path.iterdir() if p.name not in IGNORE_DIRS and not p.name.startswith(".")],
            key=lambda p: (p.is_file(), p.name),
        )
        for entry in entries:
            lines.append(f"{prefix}{entry.name}")
            if entry.is_dir():
                walk(entry, prefix + "  ", depth + 1)

    walk(root)
    return "\n".join(lines)
```

`max_depth` bounds output size — a deeply nested repo could otherwise
produce a huge wall of text. The sort key puts directories before files
(`False < True`), then alphabetical — a readability choice, not functional.

**Test:**
```python
print(build_directory_tree("repos/ai-engineering-interview-questions"))
```
**Expected shape:**
```
README.md
system-design
  README.md
  case-studies
    ...
```

## Stage 2 — Pull in key files (README, config)

Rather than parsing every file for architecture info, grab files that
conventionally already contain a human-written summary. `rglob` searches
recursively since READMEs sometimes live in subfolders. The `[:3000]` cap
keeps one giant README from blowing up prompt size later.

```python
def find_key_files(repo_path: str) -> dict:
    root = Path(repo_path)
    key_names = ["README.md", "README.rst", "package.json", "requirements.txt", "pyproject.toml"]
    found = {}
    for name in key_names:
        matches = list(root.rglob(name))
        if matches:
            found[name] = matches[0].read_text(errors="ignore")[:3000]
    return found
```

`matches[0]` only takes the first match if there are several — a Phase 1
simplification worth revisiting if the real README isn't the top-level one.

**Test:**
```python
kf = find_key_files("repos/ai-engineering-interview-questions")
print(list(kf.keys()))
print(kf.get("README.md", "")[:300])
```
**Expected:** a list containing `'README.md'` — this repo likely has no
`package.json`/`requirements.txt` since it's a content repo, not runnable
code. Confirm that matches what you actually see.

## Stage 3 — Assemble the repo map

Bundles Stage 1 + Stage 2 into one dict — this becomes a single special
chunk (`type: "structure"`) stored in Qdrant, retrievable like any other.

```python
def build_repo_map(repo_path: str) -> dict:
    return {
        "directory_tree": build_directory_tree(repo_path),
        "key_files": find_key_files(repo_path),
    }
```

**Test:**
```python
rm = build_repo_map("repos/ai-engineering-interview-questions")
print(rm["directory_tree"][:200])
print(list(rm["key_files"].keys()))
```

---

# PART C — `app/ingestion/embed_store.py`

## Stage 0 — Why this is the last piece

Chunker + repo_map produce *text*. None of it is searchable by meaning yet.
This file turns each chunk's text into a numeric vector (embedding)
capturing its meaning, stores those vectors in Qdrant, and provides
`search()` to turn a question into a vector too and find the closest stored
ones — that "closeness" is what makes semantic search work even when the
question shares no exact keywords with the code.

## Stage 1 — Load the embedding model once

Loading a `SentenceTransformer` reads weights off disk — reasonably
expensive. Doing it at module level means it happens once on import, and
every call afterward reuses the same in-memory model.

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")
```

**Test:**
```python
vec = model.encode("def foo(): return 1")
print(len(vec))
```
**Expected output:** `384`

This model always outputs a 384-dimensional vector, regardless of input
length — a fixed property of this model. This number must exactly match
what you tell Qdrant to expect (Stage 2), or every insert is rejected.

## Stage 2 — Connect to Qdrant and create a collection

A Qdrant "collection" is like a table — declare upfront the vector shape
(`size=384`) and distance metric (`COSINE` — measures the angle between
vectors, the standard choice for semantic similarity since it cares about
direction of meaning, not raw magnitude). `collection_exists` makes this
safe to call repeatedly without erroring on "already exists."

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

client = QdrantClient(host="localhost", port=6333)

def ensure_collection(name: str):
    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )
```

**Test (with `docker compose up -d` already running):**
```python
ensure_collection("codebase_chunks")
print(client.get_collections())
```
**Expected:** a response listing `codebase_chunks`.

## Stage 3 — Store chunks

Take every chunk's `content`, run all of them through the embedding model in
one batch call (batching is much faster than one-at-a-time), pair each
resulting vector back with its chunk's metadata as a `payload`. Qdrant
stores vector + payload together as a "point," identified by a random unique
ID (`uuid4()`), since chunks don't have a natural ID.

```python
import uuid
from qdrant_client.models import PointStruct

def store_chunks(chunks, repo_name: str, collection: str = "codebase_chunks"):
    ensure_collection(collection)
    texts = [c.content for c in chunks]
    vectors = model.encode(texts, show_progress_bar=True).tolist()

    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vec,
            payload={
                "repo": repo_name,
                "file_path": c.file_path,
                "function_name": c.function_name,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "content": c.content,
            },
        )
        for c, vec in zip(chunks, vectors)
    ]
    client.upsert(collection_name=collection, points=points)
    return len(points)
```

The `payload` matters: the vector alone is only useful for finding similar
chunks, it's not human-readable. The payload is what you actually get back
on a hit (file path, line numbers, original text) — without it, a search
result would be "here's a close vector" with no way to know what code it is.

**Test:**
```python
from app.ingestion.chunker import chunk_repo
from app.ingestion.embed_store import store_chunks

chunks = chunk_repo("repos/ai-engineering-interview-questions")
n = store_chunks(chunks, repo_name="ai-engineering-interview-questions")
print(f"Stored {n} chunks")
```
**Expected:** a progress bar, then `Stored <N> chunks` matching Part A
Stage 8's chunk count.

## Stage 4 — Search

Embed the *query* text with the exact same model used for storing chunks —
this consistency is essential, since different embedding models produce
vector spaces that aren't comparable to each other. Qdrant does the
nearest-neighbor math internally and returns the top-k closest stored
vectors with a `.score` (higher = more similar) plus the stored payload.

```python
def search(query: str, top_k: int = 5, collection: str = "codebase_chunks"):
    query_vec = model.encode(query).tolist()
    results = client.search(collection_name=collection, query_vector=query_vec, limit=top_k)
    return [
        {
            "score": r.score,
            "file_path": r.payload["file_path"],
            "function_name": r.payload["function_name"],
            "start_line": r.payload["start_line"],
            "end_line": r.payload["end_line"],
        }
        for r in results
    ]
```

**Test — the real end-to-end check for all of Phase 1:**
```python
results = search("how to answer system design questions")
for r in results:
    print(f"{r['score']:.3f}  {r['file_path']}:{r['start_line']}-{r['end_line']}  {r['function_name']}")
```
**Expected:** 5 results, sorted by score descending — and critically, the
top results should be topically relevant to the query. If they are, the
embedding + storage + retrieval chain works end-to-end. If the top hit is
unrelated, debug: chunks too large/mixed in content, `top_k` too small, or a
mismatch between what was actually stored and what you expect.

---

# Phase 1 "Done" checklist

- [ ] `chunker.py`: real function/class names extracted correctly, no
      duplicate nested chunks (verified with the class/2-methods test), line
      numbers verified against actual files
- [ ] `repo_map.py`: directory tree + key files pulled correctly
- [ ] `embed_store.py`: chunks stored in Qdrant, `search()` returns
      topically relevant results for a real query
- [ ] Tested against at least one code-heavy repo (not just a
      Markdown-only one) so the function-extraction path is actually proven
