from pathlib import Path
from dataclasses import dataclass, field
from tree_sitter import Parser, Language
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjs
import tree_sitter_java as tsjava

PY_LANGUAGE = Language(tspython.language())
JS_LANGUAGE = Language(tsjs.language())
JAVA_LANGUAGE = Language(tsjava.language())

FUNCTION_NODE_TYPES = {
    "function_definition", "class_definition",       # python
    "function_declaration", "method_definition",     # js/ts
    "method_declaration", "constructor_declaration", # java
}

IMPORT_NODE_TYPES = {
    "python": {"import_statement", "import_from_statement"},
    "javascript": {"import_statement"},
    "java": {"import_declaration"},
}

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

@dataclass
class CodeChunk:
    file_path: str # let us cite which file the chunk is from
    function_name: str # the name of the function or class
    start_line: int    #aut.py:42 
    end_line: int
    content: str # actual code content of the chunk, raw to embedded
    imports: list[str] = field(default_factory=list) # it maintain dependency graph

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
    return None, None # for anythig else like README.md, .txt, .json, .yml, .csv, etc. we will ignore for now

def extract_imports(root_node, source:bytes, lang:str) -> list[str]:
    imports = []
    target_types = IMPORT_NODE_TYPES.get(lang, set())

    def walk_node(node):
        if node.type in target_types:
            import_text = source[node.start_byte:node.end_byte].decode(errors = "ignore").strip()
            imports.append(import_text)
        for child in node.children:
            walk_node(child)
    walk_node(root_node)
    return imports


def extract_chunks(root_node, source:bytes, file_path:str, imports:list[str]):
    chunks = []
    def walk_node(node):
        if node.type in FUNCTION_NODE_TYPES:
            name_node = next((c for c in node.children if c.type in ("identifier", "property_identifier", "constructor")), None) # iterator, load each one by one.
            name = name_node.text.decode(errors="ignore").strip() if name_node else "anonymous"
            start_line = node.start_point.row + 1 # Point.row is 0-based; convert to 1-based line number
            end_line = node.end_point.row + 1
            content = source[node.start_byte:node.end_byte].decode(errors="ignore").strip()
            chunks.append(CodeChunk(file_path=file_path, function_name=name, start_line=start_line, end_line=end_line, content=content, imports=imports))

            return # we don't need to go deeper into this function/class node, as we already captured it

        
        for child in node.children:
            walk_node(child)
    walk_node(root_node)
    return chunks


def chunk_file(file_path: str) -> list[CodeChunk]:
    parser, lang = _get_parser_and_lang(file_path)
    source = Path(file_path).read_bytes()
    if parser is None:
        text = source.decode("utf-8", errors="ignore")
        return [CodeChunk(file_path, "FILE", 1, text.count("\n") + 1, text)]

    tree = parser.parse(source)
    imports = extract_imports(tree.root_node, source, lang)
    chunks = extract_chunks(tree.root_node, source, file_path, imports)

    if not chunks:
        text = source.decode("utf-8", errors="ignore")
        return [CodeChunk(file_path, "FILE", 1, text.count("\n") + 1, text, imports)]

    return chunks


def chunk_repo(repo_path:str)->list[CodeChunk]:
    all_chunks = []
    for path in Path(repo_path).rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.suffix in (".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".md"):
            try:
                all_chunks.extend(chunk_file(str(path)))
            except Exception as e:
                print(f"Error processing {path}: {e}")
    return all_chunks







