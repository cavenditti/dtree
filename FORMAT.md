# Format specification

Below is a **minimal specification** for a tree notation that includes:

1. **Basic directory/file prefixes** (`d:` and `f:`)
2. **Sub-file symbols** for functions and variables (`fn:` and `var:`)
3. **A simple syntax** for function parameters and return values

---

## Tree Node Syntax

1. **Each node** is specified on a separate line.
2. **Children** of a node are indented (e.g., by two spaces) below that node.
3. **Prefixes** indicate the node type:
   - `d: <directoryName>` for a directory
   - `f: <fileName>` for a file
   - `fn: <functionSignature>` for a function defined in a file
   - `var: <variableName>` for a variable defined in a file

---

## Function Signature Notation

- **Prefix**: `fn:`
- **Syntax**:
  \[
    fn: functionName(param1Name: param1Type, param2Name: param2Type, ...) -> returnType
  \]

  - **Parentheses** enclose a comma-separated list of parameters.
  - Each parameter is written as `<paramName>: <paramType>`.
  - `-> returnType` indicates the function’s return type. If a function returns nothing, you can use `-> void` or omit entirely (depending on your needs).

---

## Variable Notation

- **Prefix**: `var:`
- **Syntax**:
  \[
    var: variableName
  \]

  (Optionally, you could add type info, e.g., `var: variableName: type`, if desired.)

---

## Example

```plaintext
d: root
  d: subfolder1
    f: sample.js
      fn: greet(name: string) -> void
      var: greeting
    d: helpers
      f: utils.js
        fn: parseData(data: any) -> string
        var: configPath
  f: readme.md
```

- **root** is a directory containing:
  - **subfolder1** (directory)
    - **sample.js** (file)
      - `greet` function with a `name: string` parameter returning `void`
      - `greeting` variable
    - **helpers** (directory)
      - **utils.js** (file)
        - `parseData` function with `data: any` returning `string`
        - `configPath` variable
  - `readme.md` (file)

This structure allows:
- **Simple** directory/file hierarchy via `d:` and `f:`.
- **In-file** symbols via short prefixes (`fn:` and `var:`) for a language-aware breakdown of the file contents.

You can extend this notation (e.g., adding `cl:` for classes, `int:` for interfaces) as your use case requires.
