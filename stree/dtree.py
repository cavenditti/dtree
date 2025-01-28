import os
import stat
import pwd


def get_unix_permissions(mode: int) -> str:
    """
    Convert a file's mode (from os.stat) into a Unix-like permission string.
    E.g., 'drwxr-xr-x', 'rw-r--r--', etc.
    """
    return stat.filemode(mode)


def get_owner_name(uid: int) -> str:
    """
    Retrieve the owner (username) from a user ID using pwd.
    If not found, fall back to the numeric UID.
    """
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def format_entry(
    is_dir: bool,
    name: str,
    permissions: str,
    owner: str,
    size: int | None,
    indent_level: int,
) -> str:
    """
    Format a single line for either a directory or a file, with indentation.
    Example:
        d: subfolder1 [drwxr-xr-x | alice | 4096]
    """
    type_marker = "d" if is_dir else "f"
    indent_spaces = "  " * indent_level  # 2 spaces per level
    if size is not None:
        return (
            f"{indent_spaces}{type_marker}: {name} [{permissions} | {owner} | {size}]"
        )
    return f"{indent_spaces}{type_marker}: {name}"


def scan_directory(
    path: str,
    with_extras: bool,
    indent_level: int = 0,
) -> None:
    """
    Recursively scan 'path' using os.scandir and print entries in a
    compact tree format with permissions, owner, size.
    """
    # Use scandir to get a DirEntry object which can reduce syscalls
    try:
        entries = list(os.scandir(path))
    except (NotADirectoryError, PermissionError):
        # If it's not a directory or not accessible, handle as a single file or skip
        return

    # Sort entries by name to have a deterministic output
    entries.sort(key=lambda e: e.name)

    for entry in entries:
        # For each entry, gather stat info just once
        try:
            st = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            # The file might disappear during the scan
            continue

        # Check if directory or file
        is_directory = entry.is_dir(follow_symlinks=False)
        permissions = get_unix_permissions(st.st_mode) if with_extras else ""
        owner = get_owner_name(st.st_uid) if with_extras else ""
        size = st.st_size if with_extras else None

        line = format_entry(
            is_directory, entry.name, permissions, owner, size, indent_level
        )
        print(line)

        # Recurse into subdirectories
        if is_directory:
            scan_directory(entry.path, with_extras, indent_level + 1)


def print_compact_tree_scandir(
    start_path: str,
    with_extras: bool = False,
) -> None:
    """
    Print the root directory first, then recurse.

    Optionally include permissions, owner, and size.

    Example output:
        d: root [drwxr-xr-x | alice | 4096]
          f: file1 [-rw-r--r-- | alice | 1234]
          d: subfolder1 [drwxr-xr-x | alice | 4096]
            f: subfile1 [-rw-r--r-- | alice | 1234]
            f: subfile2 [-rw-r--r-- | alice | 1234]
          d: subfolder2 [drwxr-xr-x | alice | 4096]
            f: subfile3 [-rw-r--r-- | alice | 1234]


    Args:
        start_path: The directory to start scanning.
        with_perms: Include owner and permissions in the output.
        with_size: Include size in the output.
    """
    # Print info about the top-level item
    try:
        st = os.stat(start_path)
    except FileNotFoundError:
        return  # The path doesn't exist

    perms = get_unix_permissions(st.st_mode) if with_extras else ""
    owner = get_owner_name(st.st_uid) if with_extras else ""
    size = st.st_size if with_extras else None
    is_dir = os.path.isdir(start_path)
    name = os.path.basename(start_path) or start_path
    print(format_entry(is_dir, name, perms, owner, size, 0))

    # If it's a directory, drill down
    if is_dir:
        scan_directory(start_path, with_extras, 1)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python fast_compact_tree.py <directory>")
        sys.exit(1)
    print_compact_tree_scandir(sys.argv[1])
