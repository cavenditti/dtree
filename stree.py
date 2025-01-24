#!/usr/bin/env python3

import os
import sys
import stat
import pwd
import json
import subprocess
import time

try:
    import pathspec  # pip install pathspec if you want .gitignore support
except ImportError:
    pathspec = None

# ------------------------------------------------------------------------------
# ---------------------------  CONFIGURATION  -----------------------------------
# ------------------------------------------------------------------------------

LANGUAGE_SERVER_COMMAND = ["jedi-language-server"]  # Adjust if needed

# If you only want LSP symbols for certain extensions, set this list. Example:
ALLOWED_EXTENSIONS = [".py"]  
# ALLOWED_EXTENSIONS = None   # Attempt all files

# Mapping from LSP SymbolKind -> short prefix
SYMBOL_KIND_MAP = {
    1: "f:",
    2: "d:",
    3: "d:",
    4: "d:",
    5: "cl:",
    6: "fn:",
    7: "var:",
    8: "var:",
    9: "fn:",
    10: "enum:",
    11: "int:",
    12: "fn:",
    13: "var:",
    14: "var:",
    15: "str:",
    16: "num:",
    17: "bool:",
    18: "arr:",
    19: "obj:",
    20: "key:",
    21: "null:",
    22: "mem:",
    23: "str:",
    24: "event:",
    25: "oper:",
    26: "typ:",
}

# ------------------------------------------------------------------------------
# ---------------------------  FILESYSTEM HELPERS  ------------------------------
# ------------------------------------------------------------------------------

def get_unix_permissions(mode: int) -> str:
    return stat.filemode(mode)

def get_owner_name(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)

# ------------------------------------------------------------------------------
# ---------------------------  GITIGNORE SUPPORT  -------------------------------
# ------------------------------------------------------------------------------

def load_gitignore_spec(start_directory: str):
    if pathspec is None:
        return None
    gitignore_path = os.path.join(start_directory, ".gitignore")
    if not os.path.isfile(gitignore_path):
        return None
    with open(gitignore_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)

def is_ignored(spec, root_dir, full_path, also_ignore_hidden=False):
    base_name = os.path.basename(full_path)

    # Skip hidden if requested
    if also_ignore_hidden and base_name.startswith("."):
        return True

    if spec is None:
        return False

    rel_path = os.path.relpath(full_path, start=root_dir).replace("\\", "/")
    return spec.match_file(rel_path)

# ------------------------------------------------------------------------------
# ---------------------------  TREE DATA STRUCTURES  ----------------------------
# ------------------------------------------------------------------------------

class TreeNode:
    """
    Each node holds:
      - name
      - path (absolute path)
      - node_type: 'dir'|'file'|'symbol'
      - optional LSP symbol_kind (e.g., "fn:", "cl:", etc.)
      - children
    """
    def __init__(
        self,
        name: str,
        path: str,
        node_type: str,
        permissions: str = "",
        owner: str = "",
        size: int = None,
        symbol_kind: str = "",
    ):
        self.name = name
        self.path = path  # absolute path
        self.node_type = node_type
        self.permissions = permissions
        self.owner = owner
        self.size = size
        self.symbol_kind = symbol_kind
        self.children = []

    def add_child(self, child: "TreeNode"):
        self.children.append(child)

def print_merged_tree(node: TreeNode, indent: int = 0):
    indent_str = "  " * indent
    if node.node_type == "dir":
        if node.permissions or node.owner or node.size:
            print(f"{indent_str}d: {node.name} [{node.permissions} | {node.owner} | {node.size}]")
        else:
            print(f"{indent_str}d: {node.name}")
    elif node.node_type == "file":
        if node.permissions or node.owner or node.size:
            print(f"{indent_str}f: {node.name} [{node.permissions} | {node.owner} | {node.size}]")
        else:
            print(f"{indent_str}f: {node.name}")
    else:
        # Symbol
        print(f"{indent_str}{node.symbol_kind} {node.name}")

    for c in node.children:
        print_merged_tree(c, indent + 1)

# ------------------------------------------------------------------------------
# ---------------------------  BUILD FILESYSTEM TREE  ---------------------------
# ------------------------------------------------------------------------------

def build_filesystem_tree(
    start_path: str,
    with_extras=False,
    gitignore_spec=None,
    root_for_ignores=None,
    ignore_hidden=False,
) -> TreeNode:
    """
    Recursively build a TreeNode from start_path, storing absolute paths
    and skipping .gitignore or hidden files if requested.
    """
    if is_ignored(gitignore_spec, root_for_ignores, start_path, also_ignore_hidden=ignore_hidden):
        return None

    try:
        st = os.stat(start_path)
    except FileNotFoundError:
        return None

    name = os.path.basename(start_path) or start_path
    abs_path = os.path.abspath(start_path)
    is_dir = os.path.isdir(abs_path)

    perms = get_unix_permissions(st.st_mode) if with_extras else ""
    owner = get_owner_name(st.st_uid) if with_extras else ""
    size = st.st_size if with_extras else None

    node_type = "dir" if is_dir else "file"
    root_node = TreeNode(
        name=name,
        path=abs_path,
        node_type=node_type,
        permissions=perms,
        owner=owner,
        size=size,
    )

    if is_dir:
        try:
            entries = sorted(os.scandir(abs_path), key=lambda e: e.name)
        except (NotADirectoryError, PermissionError):
            return root_node
        for entry in entries:
            child_node = build_filesystem_tree(
                entry.path,
                with_extras=with_extras,
                gitignore_spec=gitignore_spec,
                root_for_ignores=root_for_ignores,
                ignore_hidden=ignore_hidden,
            )
            if child_node:
                root_node.add_child(child_node)

    return root_node

# ------------------------------------------------------------------------------
# ---------------------------  LSP COMMUNICATION  -------------------------------
# ------------------------------------------------------------------------------

_request_id = 0

def send_request(process, method, params=None):
    global _request_id
    _request_id += 1
    req_id = _request_id
    body = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
    }
    if params is not None:
        body["params"] = params
    text = json.dumps(body)
    message = f"Content-Length: {len(text)}\r\n\r\n{text}"
    process.stdin.write(message)
    process.stdin.flush()
    return req_id

def send_notification(process, method, params=None):
    body = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        body["params"] = params
    text = json.dumps(body)
    message = f"Content-Length: {len(text)}\r\n\r\n{text}"
    process.stdin.write(message)
    process.stdin.flush()

def read_message(process):
    headers = {}
    while True:
        line = process.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if line == "":
            break
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    content_length = int(headers.get("content-length", 0))
    if content_length == 0:
        return None

    body = process.stdout.read(content_length)
    return json.loads(body) if body else None

def start_language_server():
    return subprocess.Popen(
        LANGUAGE_SERVER_COMMAND,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,  # or subprocess.PIPE for separate error capture
        text=True,
        bufsize=0,
    )

def kind_map(symbol_kind: int) -> str:
    return SYMBOL_KIND_MAP.get(symbol_kind, "??:")

# ------------------------------------------------------------------------------
# ---------------------  SYMBOL PARSING (DocSym / SymInfo)  ---------------------
# ------------------------------------------------------------------------------

class SymbolNode:
    """
    We store the symbol name, short prefix (kind), and any children.
    If it's a function, we try to incorporate the signature from 'detail'.
    """
    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind
        self.children = []

def parse_document_symbols(doc_syms: list) -> list[SymbolNode]:
    """
    doc_syms: list of DocumentSymbol objects, each might have "children", "detail".
    """
    def from_doc_symbol(ds):
        k = kind_map(ds["kind"])
        nm = ds["name"]
        detail = ds.get("detail", "")
        if k.startswith("fn:") and detail:
            nm = f"{nm} {detail}"
        node = SymbolNode(nm, k)
        for c in ds.get("children", []):
            node.children.append(from_doc_symbol(c))
        return node
    return [from_doc_symbol(d) for d in doc_syms]

def parse_symbol_information(sym_info: list) -> list[SymbolNode]:
    """
    sym_info: list of SymbolInformation (flat). No 'detail' or 'children'.
    We'll lose function signatures, but we can still show them at top-level.
    """
    out = []
    for si in sym_info:
        k = kind_map(si["kind"])
        nm = si["name"]
        out.append(SymbolNode(nm, k))
    return out

# ------------------------------------------------------------------------------
# --------------------  DIDOPEN + DOCUMENTSYMBOL PER FILE  ---------------------
# ------------------------------------------------------------------------------

def did_open_file(lsp_proc, file_path: str, language_id="python"):
    """
    Send 'textDocument/didOpen' so the server will parse the file and return
    nested DocumentSymbol with detail (if it supports that).
    """
    uri = f"file://{os.path.abspath(file_path)}"
    text = ""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    except:
        pass

    params = {
        "textDocument": {
            "uri": uri,
            "languageId": language_id,
            "version": 1,
            "text": text
        }
    }
    send_notification(lsp_proc, "textDocument/didOpen", params)
    # let the server parse
    time.sleep(0.2)

def collect_document_symbols_for_file(lsp_proc, file_path: str) -> list[SymbolNode]:
    """
    1) didOpen -> server can parse the file
    2) textDocument/documentSymbol -> hopefully returns DocumentSymbol[] with children + detail
       If we get SymbolInformation[], we parse that flatly.
    """
    abs_path = os.path.abspath(file_path)
    did_open_file(lsp_proc, abs_path, language_id="python")

    file_uri = f"file://{abs_path}"
    params = {"textDocument": {"uri": file_uri}}
    req_id = send_request(lsp_proc, "textDocument/documentSymbol", params)

    while True:
        msg = read_message(lsp_proc)
        if not msg:
            return []
        if "id" in msg and msg["id"] == req_id:
            result = msg.get("result", [])
            if not isinstance(result, list) or not result:
                return []
            # Distinguish DocumentSymbol from SymbolInformation
            if "children" in result[0]:  # DocumentSymbol
                return parse_document_symbols(result)
            else:                        # SymbolInformation
                return parse_symbol_information(result)

# ------------------------------------------------------------------------------
# -----------------  ATTACH LSP SYMBOLS INTO FILESYSTEM TREE  ------------------
# ------------------------------------------------------------------------------

def attach_symbols_recursive(fs_node: TreeNode, lsp_proc) -> None:
    """
    If fs_node.node_type=='file', gather symbols, then create nested symbol TreeNodes.
    If 'dir', recurse into children.
    """
    if fs_node.node_type == "file":
        if ALLOWED_EXTENSIONS is not None:
            _, ext = os.path.splitext(fs_node.path)
            if ext.lower() not in ALLOWED_EXTENSIONS:
                return

        if os.path.isfile(fs_node.path):
            syms = collect_document_symbols_for_file(lsp_proc, fs_node.path)
            for s in syms:
                sym_child = TreeNode(
                    name=s.name,
                    path=fs_node.path,  # same file
                    node_type="symbol",
                    symbol_kind=s.kind
                )
                attach_symbol_children(sym_child, s.children)
                fs_node.add_child(sym_child)

    elif fs_node.node_type == "dir":
        for child in fs_node.children:
            attach_symbols_recursive(child, lsp_proc)

def attach_symbol_children(parent_node: TreeNode, symbol_children: list[SymbolNode]) -> None:
    for s in symbol_children:
        sym_node = TreeNode(
            name=s.name,
            path=parent_node.path,
            node_type="symbol",
            symbol_kind=s.kind
        )
        parent_node.add_child(sym_node)
        attach_symbol_children(sym_node, s.children)

# ------------------------------------------------------------------------------
# ----------------------------------- MAIN -------------------------------------
# ------------------------------------------------------------------------------

def main():
    """
    Usage:
      python merged_docSymbol_tree.py <start_directory> [--extras] [--gitignore]

    Steps:
      1) Possibly load .gitignore if --gitignore is used (also skip hidden).
      2) Build the directory tree with absolute paths.
      3) Start LSP, initialize with hierarchicalDocumentSymbolSupport = True
      4) For each file, didOpen + documentSymbol
      5) Print nested symbols (and function signatures in detail if provided)
    """
    if len(sys.argv) < 2:
        print("Usage: python merged_docSymbol_tree.py <start_directory> [--extras] [--gitignore]")
        sys.exit(1)

    start_path = sys.argv[1]
    with_extras = "--extras" in sys.argv
    use_gitignore = "--gitignore" in sys.argv

    start_abs = os.path.abspath(start_path)

    gitignore_spec = None
    ignore_hidden = False
    if use_gitignore:
        ignore_hidden = True
        if pathspec is not None:
            gitignore_spec = load_gitignore_spec(start_abs)
        else:
            print("[Warning] `--gitignore` used but pathspec not installed. Will only skip hidden files.")

    # 1) Build FS tree
    fs_root = build_filesystem_tree(
        start_abs,
        with_extras=with_extras,
        gitignore_spec=gitignore_spec,
        root_for_ignores=start_abs,
        ignore_hidden=ignore_hidden
    )
    if not fs_root:
        print(f"No files found under '{start_abs}'. Exiting.")
        return

    # 2) Start LSP
    lsp_proc = start_language_server()

    # 2a) Send "initialize" with hierarchicalDocumentSymbolSupport = True
    init_params = {
        "processId": os.getpid(),
        "rootUri": f"file://{start_abs}",
        "capabilities": {
            # The key addition to encourage servers to return DocumentSymbols with children & detail
            "textDocument": {
                "documentSymbol": {
                    "hierarchicalDocumentSymbolSupport": True
                }
            }
        },
        "workspaceFolders": None,
    }
    init_id = send_request(lsp_proc, "initialize", init_params)

    while True:
        msg = read_message(lsp_proc)
        if not msg:
            print("No response from LSP. Exiting.")
            lsp_proc.terminate()
            lsp_proc.wait()
            return
        if "id" in msg and msg["id"] == init_id:
            # 2b) "initialized" notification
            send_notification(lsp_proc, "initialized", {})
            break

    # 3) Attach symbols (recursively)
    attach_symbols_recursive(fs_root, lsp_proc)

    # 4) Print
    print_merged_tree(fs_root)

    # 5) Shutdown
    shutdown_id = send_request(lsp_proc, "shutdown")
    while True:
        msg = read_message(lsp_proc)
        if not msg:
            break
        if "id" in msg and msg["id"] == shutdown_id:
            break

    send_notification(lsp_proc, "exit")
    lsp_proc.terminate()
    lsp_proc.wait()


if __name__ == "__main__":
    main()
