#!/usr/bin/env python3

import os
import sys
import stat
import pwd
import json
import subprocess
import time

import pathspec
from contextlib import asynccontextmanager
from fastapi import FastAPI

LANGUAGE_SERVER_COMMAND = ["jedi-language-server"]  # Adjust if needed
ALLOWED_EXTENSIONS = [".py"]

SYMBOL_KIND_MAP = {
    1: "f:",  # File
    2: "mod:",  # Module
    3: "mod:",  # Namespace
    4: "mod:",  # Package
    5: "cls:",  # Class
    6: "fn:",  # Method
    7: "var:",  # Property
    8: "var:",  # Field
    9: "fn:",  # Constructor
    10: "enum:",  # Enum
    11: "int:",  # Interface
    12: "fn:",  # Function
    13: "var:",  # Variable
    14: "var:",  # Constant
    15: "str:",  # String
    16: "num:",  # Number
    17: "bool:",  # Boolean
    18: "arr:",  # Array
    19: "obj:",  # Object
    20: "key:",  # Key
    21: "null:",  # Null
    22: "emem:",  # EnumMember
    23: "str:",  # Struct
    24: "event:",  # Event
    25: "oper:",  # Operator
    26: "typ:",  # TypeParameter
}


def get_unix_permissions(mode: int) -> str:
    return stat.filemode(mode)


def get_owner_name(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def load_gitignore_spec(start_directory: str):
    gitignore_path = os.path.join(start_directory, ".gitignore")
    if not os.path.isfile(gitignore_path):
        return None
    with open(gitignore_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def is_ignored(spec, root_dir, full_path, also_ignore_hidden=False):
    base_name = os.path.basename(full_path)
    if also_ignore_hidden and base_name.startswith("."):
        return True
    if spec is None:
        return False
    rel_path = os.path.relpath(full_path, start=root_dir).replace("\\", "/")
    return spec.match_file(rel_path)


class TreeNode:
    def __init__(
        self,
        name: str,
        path: str,
        node_type: str,
        permissions: str = "",
        owner: str = "",
        size: int | None = None,
        symbol_kind: str = "",
    ):
        self.name = name
        self.path = path
        self.node_type = node_type
        self.permissions = permissions
        self.owner = owner
        self.size = size
        self.symbol_kind = symbol_kind
        self.children = []

    def add_child(self, child: "TreeNode"):
        self.children.append(child)


def print_merged_tree(node: "TreeNode", indent: int = 0):
    indent_str = "  " * indent
    if node.node_type == "dir":
        if node.permissions or node.owner or node.size:
            print(
                f"{indent_str}d: {node.name} [{node.permissions} | {node.owner} | {node.size}]"
            )
        else:
            print(f"{indent_str}d: {node.name}")
    elif node.node_type == "file":
        if node.permissions or node.owner or node.size:
            print(
                f"{indent_str}f: {node.name} [{node.permissions} | {node.owner} | {node.size}]"
            )
        else:
            print(f"{indent_str}f: {node.name}")
    else:
        # Symbol
        print(f"{indent_str}{node.symbol_kind} {node.name}")

    for c in node.children:
        print_merged_tree(c, indent + 1)


def build_filesystem_tree(
    start_path: str,
    with_extras=False,
    gitignore_spec=None,
    root_for_ignores=None,
    ignore_hidden=False,
) -> TreeNode | None:
    if is_ignored(
        gitignore_spec, root_for_ignores, start_path, also_ignore_hidden=ignore_hidden
    ):
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


def start_language_server() -> subprocess.Popen:
    return subprocess.Popen(
        LANGUAGE_SERVER_COMMAND,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        bufsize=0,
    )


def kind_map(symbol_kind: int) -> str:
    return SYMBOL_KIND_MAP.get(symbol_kind, "??:")


class SymbolNode:
    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind
        self.children = []


def parse_document_symbols(doc_syms: list) -> list[SymbolNode]:
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
    out = []
    for si in sym_info:
        k = kind_map(si["kind"])
        nm = si["name"]
        out.append(SymbolNode(nm, k))
    return out


def did_open_file(lsp_proc, file_path: str, language_id="python"):
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
            "text": text,
        }
    }
    send_notification(lsp_proc, "textDocument/didOpen", params)
    time.sleep(0.2)


def collect_document_symbols_for_file(lsp_proc, file_path: str) -> list[SymbolNode]:
    abs_path = os.path.abspath(file_path)
    # did_open_file(lsp_proc, abs_path, language_id="python")

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
            if "children" in result[0]:  # DocumentSymbol
                return parse_document_symbols(result)
            else:  # SymbolInformation
                return parse_symbol_information(result)


def attach_symbol_children(
    parent_node: TreeNode, symbol_children: list[SymbolNode]
) -> None:
    for s in symbol_children:
        sym_node = TreeNode(
            name=s.name, path=parent_node.path, node_type="symbol", symbol_kind=s.kind
        )
        parent_node.add_child(sym_node)
        attach_symbol_children(sym_node, s.children)


def attach_symbols_recursive(fs_node: TreeNode, lsp_proc) -> None:
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
                    path=fs_node.path,
                    node_type="symbol",
                    symbol_kind=s.kind,
                )
                attach_symbol_children(sym_child, s.children)
                fs_node.add_child(sym_child)
    elif fs_node.node_type == "dir":
        for child in fs_node.children:
            attach_symbols_recursive(child, lsp_proc)


def stree(
    path: str, lsp_proc: subprocess.Popen, extras: bool, use_gitignore: bool
) -> str:
    output_lines = []
    path = os.path.abspath(path)

    gitignore_spec = None
    ignore_hidden = False
    if use_gitignore:
        ignore_hidden = True
        gitignore_spec = load_gitignore_spec(path)

    fs_root = build_filesystem_tree(
        path,
        with_extras=extras,
        gitignore_spec=gitignore_spec,
        root_for_ignores=path,
        ignore_hidden=ignore_hidden,
    )
    if not fs_root:
        output_lines.append(f"No files found under '{path}'. Exiting.")
        return "\n".join(output_lines)

    original_stdout = sys.stdout
    try:
        from io import StringIO

        buffer = StringIO()
        sys.stdout = buffer
        attach_symbols_recursive(fs_root, lsp_proc)
        print_merged_tree(fs_root)
        output_lines.append(buffer.getvalue().rstrip())
    finally:
        sys.stdout = original_stdout

    return "\n".join(output_lines)


def lsp_setup(start_path: str) -> subprocess.Popen:
    start_path = os.path.abspath(__file__)

    lsp_proc = start_language_server()
    init_params = {
        "processId": os.getpid(),
        "rootUri": f"file://{start_path}",
        "capabilities": {
            "textDocument": {
                "documentSymbol": {"hierarchicalDocumentSymbolSupport": True}
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
            exit(-1)
        if "id" in msg and msg["id"] == init_id:
            send_notification(lsp_proc, "initialized", {})
            break
    print("LSP server started.")
    return lsp_proc


def shutdown_lsp(lsp_proc: subprocess.Popen):
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


def main():
    if len(sys.argv) < 2:
        return "Usage: python stree.py <start_directory> [--extras] [--gitignore]"

    start_path = os.path.abspath(sys.argv[1])
    use_extras = "--extras" in sys.argv
    use_gitignore = "--gitignore" in sys.argv

    lsp_proc = lsp_setup(start_path)

    print(stree(start_path, lsp_proc, use_extras, use_gitignore))

    shutdown_lsp(lsp_proc)


if __name__ == "__main__":
    print(main())
else:
    start_path = __file__
    lsp_proc = lsp_setup(start_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        lsp_proc = lsp_setup(start_path)
        yield
        shutdown_lsp(lsp_proc)

    app = FastAPI(lifespan=lifespan)

    @app.get("/stree")
    def stree_endpoint(path: str, use_extras: bool = False, use_gitignore: bool = True):
        return stree(path, lsp_proc, use_extras, use_gitignore)
