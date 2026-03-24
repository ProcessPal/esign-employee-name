"""CLI interface for adding e-signature fields to PDFs."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from esign.extractor import find_text_locations
from esign.signer import add_signature_fields

app = typer.Typer(help="Add e-signature fields to PDFs at 'Employee Name' locations.")


@app.command()
def prepare(
    input_pdf: Path = typer.Argument(..., help="Input PDF file path"),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Output PDF path"),
    search_text: str = typer.Option("Employee Name", "--search-text", help="Text to search for"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing output file"),
) -> None:
    """Prepare a PDF for e-signing by adding signature fields at 'Employee Name' locations."""
    if not input_pdf.exists():
        typer.echo(f"Error: Input file not found: {input_pdf}", err=True)
        raise typer.Exit(2)

    try:
        pdf_bytes = input_pdf.read_bytes()
    except OSError as exc:
        typer.echo(f"Error: Cannot read input file: {exc}", err=True)
        raise typer.Exit(2)

    if not pdf_bytes.startswith(b"%PDF-"):
        typer.echo(f"Error: File is not a valid PDF (missing %PDF- header): {input_pdf}", err=True)
        raise typer.Exit(2)

    if output is None:
        output = input_pdf.parent / f"{input_pdf.stem}_prepared.pdf"

    if output.exists() and not force:
        typer.echo(
            f"Error: Output file already exists: {output}. Use --force to overwrite.", err=True
        )
        raise typer.Exit(2)

    try:
        extraction = find_text_locations(pdf_bytes, search_text=search_text)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2)

    typer.echo(f"Scanned {extraction.pages_scanned} pages")

    if not extraction.locations:
        typer.echo(f"Error: '{search_text}' not found in PDF", err=True)
        raise typer.Exit(1)

    typer.echo(f"Found {len(extraction.locations)} '{search_text}' occurrence(s)")

    signer_locations = [
        (loc.page_index, loc.box, loc.page_width, loc.page_height)
        for loc in extraction.locations
    ]

    try:
        result = add_signature_fields(pdf_bytes, signer_locations)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2)

    for field in result.fields_added:
        x0, y0, x1, y1 = field.box
        typer.echo(
            f"  Added field '{field.field_name}' on page {field.page_index + 1}"
            f" at ({x0:.0f}, {y0:.0f}, {x1:.0f}, {y1:.0f})"
        )

    for field_name in result.fields_skipped:
        typer.echo(f"  Skipped field '{field_name}' (already exists)")

    try:
        output.write_bytes(result.pdf_bytes)
    except OSError as exc:
        typer.echo(f"Error: Cannot write output file: {exc}", err=True)
        raise typer.Exit(2)

    typer.echo(f"Output: {output}")
