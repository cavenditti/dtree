import stat
import pytest
from unittest.mock import patch, MagicMock

from stree import (
    get_unix_permissions,
    get_owner_name,
    load_gitignore_spec,
    is_ignored,
    build_filesystem_tree,
    attach_symbols_recursive,
    parse_document_symbols,
    parse_symbol_information,
    SymbolNode,
    start_language_server,
    send_request,
    send_notification,
    read_message,
)


@pytest.fixture
def mock_fs(tmp_path):
    """
    A pytest fixture using the built-in tmp_path.
    We create a small structure for testing build_filesystem_tree.
    """
    d = tmp_path / "folder"
    d.mkdir()
    f1 = d / "file1.py"
    f1.write_text("print('Hello world')", encoding="utf-8")

    f2 = d / "file2.txt"
    f2.write_text("Just a text file", encoding="utf-8")

    return tmp_path


def test_get_unix_permissions():
    # stat.S_IFREG => indicates a regular file
    # 0o644 => typical rw-r--r--
    mode = stat.S_IFREG | 0o644
    perms = get_unix_permissions(mode)
    assert perms == "-rw-r--r--", f"Unexpected permissions: {perms}"


@patch("pwd.getpwuid")
def test_get_owner_name(mock_getpwuid):
    mock_getpwuid.return_value.pw_name = "testuser"
    owner = get_owner_name(1001)
    assert owner == "testuser"
    mock_getpwuid.side_effect = KeyError()
    owner2 = get_owner_name(9999)
    assert owner2 == "9999"


def test_load_gitignore_spec(tmp_path):
    """
    Create a .gitignore and ensure load_gitignore_spec returns a PathSpec.
    """
    from stree import pathspec

    (tmp_path / ".gitignore").write_text("*.pyc\n__pycache__\n", encoding="utf-8")
    spec = load_gitignore_spec(str(tmp_path))
    assert spec is not None
    # Check ignoring
    assert spec.match_file("foo.pyc")
    assert spec.match_file("__pycache__")


def test_is_ignored_no_spec():
    # If there's no spec, only hidden check matters
    assert is_ignored(None, "/", "/some/.hidden", also_ignore_hidden=True) is True
    assert is_ignored(None, "/", "/some/visible", also_ignore_hidden=True) is False


def test_is_ignored_with_spec(tmp_path):
    from stree import pathspec

    # Make a mock spec that ignores *.py
    mock_lines = ["*.py"]
    spec = pathspec.PathSpec.from_lines("gitwildmatch", mock_lines)

    # The file "test.py" should be ignored
    ignored = is_ignored(spec, str(tmp_path), str(tmp_path / "test.py"))
    assert ignored is True

    # The file "test.txt" should not be ignored
    not_ignored = is_ignored(spec, str(tmp_path), str(tmp_path / "test.txt"))
    assert not_ignored is False


def test_build_filesystem_tree(mock_fs):
    """
    We created mock_fs with:
        folder/
          file1.py
          file2.txt
    We expect a directory node with 2 children.
    """
    root_path = mock_fs / "folder"
    tree = build_filesystem_tree(str(root_path))
    assert tree is not None
    assert tree.node_type == "dir"
    assert len(tree.children) == 2
    names = sorted(child.name for child in tree.children)
    assert names == ["file1.py", "file2.txt"]


@patch("stree.ALLOWED_EXTENSIONS", [".py"])
@patch("stree.collect_document_symbols_for_file")
def test_attach_symbols_recursive(mock_collect, mock_fs):
    """
    We ensure only *.py is processed for symbol collection.
    """
    # Mock LSP process with MagicMock
    fake_lsp_proc = MagicMock()

    # Fake return from collect_document_symbols_for_file
    sym_mock = [SymbolNode("func1", "fn:"), SymbolNode("ClassA", "cl:")]
    mock_collect.return_value = sym_mock

    root_path = mock_fs / "folder"
    fs_root = build_filesystem_tree(str(root_path))
    attach_symbols_recursive(fs_root, fake_lsp_proc)

    # attach_symbols_recursive should have called collect_document_symbols_for_file once
    # for file1.py (but not for file2.txt because .txt is not allowed).
    assert mock_collect.call_count == 1

    file_py_node = [c for c in fs_root.children if c.name == "file1.py"][0]
    assert len(file_py_node.children) == 2  # 2 symbols attached: func1, ClassA


def test_parse_document_symbols():
    """
    Ensure parse_document_symbols returns a nested SymbolNode structure
    from 'documentSymbol' shaped data.
    """
    doc_syms = [
        {
            "name": "MyClass",
            "kind": 5,  # class
            "detail": "class docstring",
            "children": [
                {
                    "name": "my_method",
                    "kind": 6,  # function
                    "detail": "(self, arg)",
                }
            ],
        }
    ]
    result = parse_document_symbols(doc_syms)
    assert len(result) == 1
    assert (
        result[0].name == "MyClass"
    )  # For a class, we don't usually append detail to name
    # The kind_map(5) => "cl:" by default
    assert result[0].kind == "cl:"
    assert len(result[0].children) == 1
    child = result[0].children[0]
    assert child.name == "my_method (self, arg)"
    assert child.kind == "fn:"


def test_parse_symbol_information():
    """
    SymbolInformation has no 'detail' or children in the same shape,
    so we just flatten it.
    """
    sym_info = [
        {"name": "func1", "kind": 6},
        {"name": "var1", "kind": 7},
    ]
    result = parse_symbol_information(sym_info)
    assert len(result) == 2
    assert result[0].name == "func1"
    assert result[0].kind == "fn:"
    assert result[1].name == "var1"
    assert result[1].kind == "var:"


@patch("subprocess.Popen")
def test_start_language_server(mock_popen):
    """
    Just ensure start_language_server spawns a process with the correct args.
    """
    mock_process = MagicMock()
    mock_popen.return_value = mock_process

    proc = start_language_server()
    assert proc == mock_process
    mock_popen.assert_called_once()


def test_send_request():
    """
    We can test send_request by giving a mock process and ensuring
    the correct JSON is written to stdin.
    """
    from io import StringIO

    mock_stdin = StringIO()
    mock_stdout = StringIO()
    mock_process = MagicMock()
    mock_process.stdin = mock_stdin
    mock_process.stdout = mock_stdout

    # Because _request_id is global and increments, we might want to isolate it
    # or reset it, but let's just test the structure for now.
    req_id = send_request(mock_process, "testMethod", {"param": 123})
    # The request ID must be an integer (>=1)
    assert req_id >= 1

    # Inspect what's written to mock_stdin:
    written = mock_stdin.getvalue()
    assert "Content-Length:" in written
    assert '"method": "testMethod"' in written
    assert '"param": 123' in written


def test_send_notification():
    from io import StringIO

    mock_stdin = StringIO()
    mock_stdout = StringIO()
    mock_process = MagicMock()
    mock_process.stdin = mock_stdin
    mock_process.stdout = mock_stdout

    send_notification(mock_process, "notifyMethod", {"param": 999})
    written = mock_stdin.getvalue()
    assert "Content-Length:" in written
    assert '"method": "notifyMethod"' in written
    assert '"param": 999' in written


def test_read_message():
    """
    Simulate receiving a message from the LSP server.
    """
    from io import StringIO

    body = '{"jsonrpc":"2.0","id":1,"result":["some","data"]}'
    raw = ("Content-Length: {}\r\n\r\n{}").format(len(body), body)

    mock_stdout = StringIO(raw)
    mock_stdin = StringIO()  # not used in read_message
    mock_process = MagicMock()
    mock_process.stdout = mock_stdout
    mock_process.stdin = mock_stdin

    msg = read_message(mock_process)
    assert msg["id"] == 1
    assert msg["result"] == ["some", "data"]
