# stree

A Python tool that recursively traverses the file system and queries a Language Server Protocol (LSP) server (e.g. [Jedi Language Server](https://github.com/pappasam/jedi-language-server)) to gather symbol information (classes, functions, variables, etc.). It then merges this data into a single tree structure that includes:

- File system info (directory and file structure)
- Symbol info (LSP symbols parsed for each file)

This allows you to see both the file system and the code symbols in one unified hierarchy.

> [!NOTE]
> __This is a fully AI-generated experiment.__
>
> Both code and documentation are created by o1.

---

## Features

- **Recursive File Traversal**
  Builds a tree of files and directories from a specified starting directory.

- **.gitignore Support** (optional)
  When enabled (`--gitignore`), uses [PathSpec](https://pypi.org/project/pathspec/) to skip files or folders ignored by `.gitignore`.

- **LSP Integration**
  Spawns a language server process (by default, `jedi-language-server`) and collects symbols (classes, functions, etc.) from each file using `documentSymbol` requests.

- **Customizable**
  - If you only care about certain file extensions, set `ALLOWED_EXTENSIONS`.
  - Show or hide file metadata (permissions, owner, size) with `--extras`.

---

## Requirements

- **Python 3.7+** (for type hints and f-strings).
- [Pytest](https://docs.pytest.org/en/stable/) (only for running tests).
- [jedi-language-server](https://github.com/pappasam/jedi-language-server) or any LSP server you configure in `LANGUAGE_SERVER_COMMAND`.
- (Optional) [PathSpec](https://pypi.org/project/pathspec/) for `.gitignore` support, if you use `--gitignore`.

Install requirements:

```bash
pip install jedi-language-server pathspec pytest
```

> **Note**: If you do **not** need `.gitignore` support, you can skip `pathspec`.

---

## Usage

```bash
python stree.py <start_directory> [--extras] [--gitignore]
```

- **`<start_directory>`**: Path to the directory you want to process.
- **`--extras`**: Collect extra file metadata (permissions, owner, file size) and include it in the output.
- **`--gitignore`**: Load `.gitignore` from `<start_directory>` (if present) and skip any matching files. Also skips hidden files (`.git`, etc.).

**Example**:

```bash
python stree.py . --extras --gitignore
```

When you run the script:

1. It **builds a file system tree** from the given start directory.
2. It **starts the LSP server**, sends an `initialize` request with `hierarchicalDocumentSymbolSupport = True`.
3. For each file that matches `ALLOWED_EXTENSIONS`:
   - Opens the file with `didOpen`
   - Requests `documentSymbol`
   - Parses the returned symbols and attaches them to the file node.
4. Finally, it **prints** the merged hierarchy.

When done, it sends a `shutdown` & `exit` request to the language server.

---

## Example Output

A sample snippet of output might look like:

```
d: my_project
  d: src
    f: main.py [ -rw-r--r-- | user | 1234 ]
      fn: my_function (arg1, arg2)
      cl: MyClass
        fn: __init__ (self)
  f: README.md
```

---

## Testing

This project includes **pytest** tests in `stree.py`. To run the tests:

1. Install dependencies (including `pytest`).
2. From the project root directory, run:

   ```bash
   pytest -v
   ```

Some test categories include:

- **File system building**: Validates directory and file nodes, `.gitignore` handling, etc.
- **LSP communication**: Mocks the language server process to ensure correct requests/responses.
- **Symbol parsing**: Tests `documentSymbol` vs. `symbolInformation` structures.

---

## Project Structure

- **`stree.py`**
  The main module containing all functionality:
  - File system traversal
  - LSP client routines (requests/responses)
  - Symbol parsing
  - Command-line `main()`

- **`test_stree.py`**
  Contains **pytest** tests for each core function and use-case scenario.

---

## Customizing

- **Language Server**: If you prefer a different language server, edit the `LANGUAGE_SERVER_COMMAND` list in `stree.py`.
- **Allowed Extensions**: Edit `ALLOWED_EXTENSIONS`. A value of `None` attempts to process **all files**.
- **SymbolKind Mapping**: Adjust the `SYMBOL_KIND_MAP` dictionary to alter the prefix for each kind (e.g. `cl:` for class, `fn:` for function, etc.).

---

## Contributing

Contributions and suggestions are welcome! Feel free to open an issue or pull request to fix bugs, add features, or improve documentation/tests.

---

## License

This project is distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
