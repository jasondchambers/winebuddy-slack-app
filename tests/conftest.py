"""Helpers shared by the step definitions."""


def unescape(text: str) -> str:
    r"""Turn backslash escapes written in a feature file (\n, \x00) into the characters they stand for."""
    return text.encode("latin-1", "backslashreplace").decode("unicode_escape")


def table_rows(datatable: list[list[str]]) -> list[dict]:
    """Turn a feature-file table (header row first) into one dict per row, unescaping each cell."""
    header, *rows = datatable
    return [dict(zip(header, (unescape(c) for c in row), strict=True)) for row in rows]
