from __future__ import annotations

from pathlib import Path
from typing import Any

import pypandoc
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("pypandoc")


def _normalize_extra_args(extra_args: list[str] | None) -> list[str]:
    if not extra_args:
        return []
    return [str(item) for item in extra_args if str(item).strip()]


@mcp.tool(description="Get installed pandoc version.")
def pandoc_version() -> dict[str, Any]:
    return {"version": pypandoc.get_pandoc_version()}


@mcp.tool(description="List available pandoc input and output formats.")
def pandoc_formats() -> dict[str, Any]:
    inputs, outputs = pypandoc.get_pandoc_formats()
    return {
        "input_formats": sorted(inputs),
        "output_formats": sorted(outputs),
    }


@mcp.tool(description="Convert text using pandoc.")
def convert_text(
    text: str,
    to: str,
    format: str = "markdown",
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    converted = pypandoc.convert_text(
        source=text,
        to=to,
        format=format,
        extra_args=_normalize_extra_args(extra_args),
    )
    return {
        "to": to,
        "format": format,
        "result": converted,
    }


@mcp.tool(description="Convert a file using pandoc. If output_path is empty, returns converted text.")
def convert_file(
    input_path: str,
    to: str,
    format: str | None = None,
    output_path: str | None = None,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    src = Path(input_path).expanduser().resolve()
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"input file not found: {src}")

    outputfile = None
    if output_path:
        outputfile = str(Path(output_path).expanduser().resolve())

    result = pypandoc.convert_file(
        source_file=str(src),
        to=to,
        format=format,
        outputfile=outputfile,
        extra_args=_normalize_extra_args(extra_args),
    )

    if outputfile:
        return {
            "to": to,
            "format": format,
            "input_path": str(src),
            "output_path": outputfile,
            "written": True,
        }

    return {
        "to": to,
        "format": format,
        "input_path": str(src),
        "written": False,
        "result": result,
    }


@mcp.tool(description="Download and install pandoc binary if missing.")
def ensure_pandoc() -> dict[str, Any]:
    try:
        version = pypandoc.get_pandoc_version()
        return {"installed": True, "version": version}
    except OSError:
        pypandoc.download_pandoc()
        version = pypandoc.get_pandoc_version()
        return {"installed": True, "version": version}


if __name__ == "__main__":
    mcp.run(transport="stdio")
