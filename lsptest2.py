#!/usr/bin/env python3

import json
import subprocess
import sys
import os

# ---------------------------
# Configuration
# ---------------------------
LANGUAGE_SERVER_COMMAND = [
    "pylsp"
]  # Example: Python Language Server ("pyls" or "python -m pylsp")
WORKSPACE_FOLDER = os.path.abspath(".")  # Adjust to your workspace
USE_WORKSPACE_SYMBOL = (
    True  # If True, uses workspace/symbol. Otherwise, use textDocument/documentSymbol.
)

# Example mapping from LSP SymbolKind (1-based) to our short prefixes
# SymbolKind reference: https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_documentSymbol

SYMBOL_KIND_MAP = {
    1: "f:",  # File
    2: "d:",  # Module
    3: "d:",  # Namespace
    4: "d:",  # Package
    5: "cl:",  # Class
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
    19: "obj",  # Object
    20: "key",  # Key
    21: "null",  # Null
    22: "mem",  # EnumMember
    23: "str",  # Struct
    24: "event",  # Event
    25: "oper",  # Operator
    26: "typ",  # TypeParameter
}

# ---------------------------
# Helper: Write a JSON-RPC message to LSP server
# ---------------------------
_request_id = 0


def send_request(process, method, params=None):
    """
    Send a JSON-RPC request to the LSP server via stdin.
    Returns the request id used, so we can match the response.
    """
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


# ---------------------------
# Helper: Read JSON-RPC responses
# ---------------------------
def read_message(process):
    """
    Reads a single JSON-RPC message from the LSP server (blocking).
    Returns the parsed JSON object or None if something unexpected happens.
    """
    # First, read headers until an empty line
    headers = {}
    while True:
        line = process.stdout.readline()
        if not line:
            return None  # Server closed?
        line = line.strip()
        if line == "":
            # End of headers
            break
        # e.g. "Content-Length: 123"
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    content_length = int(headers.get("content-length", 0))
    if content_length == 0:
        return None

    # Now read the JSON body
    body = process.stdout.read(content_length)
    return json.loads(body)


# ---------------------------
# Start LSP server
# ---------------------------
def start_language_server():
    """
    Launch the LSP server as a subprocess.
    Returns the subprocess.Popen instance.
    """
    return subprocess.Popen(
        LANGUAGE_SERVER_COMMAND,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,  # or subprocess.PIPE if you want to capture errors
        text=True,  # ensures we're working with strings, not bytes
        bufsize=0,  # unbuffered, so we can read line by line
    )


# ---------------------------
# Build a tree structure
# ---------------------------
class SymbolNode:
    """
    Basic tree node to hold symbol info and children.
    """

    def __init__(self, name, kind, children=None):
        self.name = name
        self.kind = kind  # e.g. "f:", "d:", "fn:", "var:", ...
        self.children = children if children else []


def add_symbol_to_tree(root, symbol):
    """
    In a real scenario, you might parse file paths or URIs from the symbol to build a
    file/directory hierarchy. For simplicity, we put everything under 'root' or do
    naive grouping.

    This is *not* a fully correct approach for all language servers, but it shows
    the concept of building a tree.
    """
    node = SymbolNode(symbol["name"], kind_map(symbol["kind"]))
    root.children.append(node)


def add_doc_symbol(parent, sym):
    """
    Recursively add a DocumentSymbol to the tree.

    This function assumes that the input is a DocumentSymbol object.
    """
    node = SymbolNode(sym["name"], kind_map(sym["kind"]))
    parent.children.append(node)
    for child in sym.get("children", []):
        add_doc_symbol(node, child)


def get_or_create_node(name, parent):
    """
    Find a child node by name or create a new one.

    This function assumes that the parent node has a 'children' list.
    """
    for c in parent.children:
        if c.name == name:
            return c
    new_node = SymbolNode(name, "d:")  # default kind for containers
    parent.children.append(new_node)
    return new_node


def kind_map(symbol_kind):
    """
    Map LSP symbolKind to our short prefixes.
    """
    return SYMBOL_KIND_MAP.get(symbol_kind, "??:")


def print_tree(node, indent=0):
    prefix = "  " * indent
    print(f"{prefix}{node.kind} {node.name}")
    for child in node.children:
        print_tree(child, indent + 1)


# ---------------------------
# Main flow
# ---------------------------
def main(path: str):
    # 1) Start the LSP server
    lsp = start_language_server()

    # 2) Send "initialize" request
    init_params = {
        "processId": os.getpid(),
        "rootUri": f"file://{WORKSPACE_FOLDER}",
        "capabilities": {},  # Minimal capabilities
        "workspaceFolders": None,
    }
    init_id = send_request(lsp, "initialize", init_params)

    # 3) Read messages until we get the initialize response
    initialized = False
    while True:
        msg = read_message(lsp)
        # print(json.dumps(msg, indent=2))
        if not msg:
            break
        if "id" in msg and msg["id"] == init_id:
            # "initialize" response
            # Typically, the server might return capabilities, etc.
            # Now send an "initialized" notification (no id)
            send_request(
                lsp, "initialized", {}
            )  # LSP says this is a notification, but many servers accept it either way
            initialized = True

            if (
                "workspaceSymbolProvider"
                not in msg["result"]["capabilities"]["workspace"]
                or not msg["result"]["capabilities"]["workspace"][
                    "workspaceSymbolProvider"
                ]
            ):
                print("Server does not support workspace/symbol.", file=sys.stderr)
                global USE_WORKSPACE_SYMBOL
                USE_WORKSPACE_SYMBOL = False
            break

    if not initialized:
        print("Failed to initialize LSP server.", file=sys.stderr)
        return

    # 4) Request symbols
    # Option A: workspace/symbol to get all symbols in the workspace
    if USE_WORKSPACE_SYMBOL:
        symbol_params = {
            "query": ""  # an empty query might return all symbols for some servers
        }
        symbol_req_id = send_request(lsp, "workspace/symbol", symbol_params)

    # Option B: textDocument/documentSymbol for a single file
    else:
        example_file_uri = f"file://{WORKSPACE_FOLDER}/{path}"
        symbol_params = {"textDocument": {"uri": example_file_uri}}
        symbol_req_id = send_request(lsp, "textDocument/documentSymbol", symbol_params)

    # 5) Read messages until we find the one matching `symbol_req_id`
    symbols_response = None

    while True:
        msg = read_message(lsp)
        print(json.dumps(msg, indent=2))
        if not msg:
            break
        if "id" in msg and msg["id"] == symbol_req_id:
            # This is our response
            symbols_response = msg["result"]
            break

    if not symbols_response:
        print("No symbols returned by the LSP server.", file=sys.stderr)
        return

    # 6) Build a simple tree from the returned symbols
    root_node = SymbolNode(
        path, "d:" if os.path.isdir(path) else "f:"
    )  # top-level placeholder

    # The response shape differs depending on 'workspace/symbol' vs. 'documentSymbol':
    # - `workspace/symbol` returns an array of SymbolInformation
    # - `documentSymbol` returns nested DocumentSymbol objects
    # For simplicity, handle the array-of-SymbolInformation scenario:
    # Each SymbolInformation has: name, kind, location, containerName (optional), ...
    if (
        isinstance(symbols_response, list)
        and symbols_response
        and "location" in symbols_response[0]
    ):
        # Likely workspace/symbol array (SymbolInformation). Use containerName to nest.
        symbol_map = {}

        for sym in symbols_response:
            container = sym.get("containerName")
            if container:
                parent = get_or_create_node(container, root_node)
                add_symbol_to_tree(parent, sym)
            else:
                add_symbol_to_tree(root_node, sym)
    else:
        # Likely documentSymbol array (DocumentSymbol). Recursively handle children.

        for s in symbols_response:
            add_doc_symbol(root_node, s)

    # 7) Print the resulting tree
    print_tree(root_node)

    # 8) Send "shutdown" and "exit" to gracefully close the LSP server
    shutdown_id = send_request(lsp, "shutdown")
    # read shutdown response
    while True:
        msg = read_message(lsp)
        if not msg:
            break
        if "id" in msg and msg["id"] == shutdown_id:
            break

    # After shutdown, send "exit" (notification)
    send_request(lsp, "exit", None)

    lsp.terminate()
    lsp.wait()


if __name__ == "__main__":
    main(os.path.basename(__file__))
