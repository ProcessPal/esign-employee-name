"""Tests for src/esign/cli.py — Typer CLI interface."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from esign.cli import app

FIXTURES_DIR = Path(__file__).parent / "fixtures"

runner = CliRunner()


def _fixture(name: str) -> Path:
    return FIXTURES_DIR / name


def _copy_fixture(name: str, dest_dir: Path) -> Path:
    """Copy a fixture PDF to dest_dir and return the new path."""
    src = _fixture(name)
    dst = dest_dir / name
    shutil.copy2(src, dst)
    return dst


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_prepare_success(tmp_path: Path) -> None:
    """Run with sample.pdf, expect exit 0, output file created, 'Added field' in output."""
    input_pdf = _copy_fixture("sample.pdf", tmp_path)
    output_pdf = tmp_path / "out.pdf"

    result = runner.invoke(app, [str(input_pdf), "-o", str(output_pdf)])

    assert result.exit_code == 0, result.output
    assert output_pdf.exists()
    assert output_pdf.stat().st_size > 0
    assert "Added field" in result.output


def test_prepare_output_flag(tmp_path: Path) -> None:
    """Run with -o flag, verify the custom output path is used."""
    input_pdf = _copy_fixture("sample.pdf", tmp_path)
    custom_output = tmp_path / "custom_output.pdf"

    result = runner.invoke(app, [str(input_pdf), "-o", str(custom_output)])

    assert result.exit_code == 0, result.output
    assert custom_output.exists()
    assert f"Output: {custom_output}" in result.output


def test_prepare_default_output_name(tmp_path: Path) -> None:
    """Run without -o, verify output is {input_stem}_prepared.pdf in same directory."""
    input_pdf = _copy_fixture("sample.pdf", tmp_path)
    expected_output = tmp_path / "sample_prepared.pdf"

    result = runner.invoke(app, [str(input_pdf)])

    assert result.exit_code == 0, result.output
    assert expected_output.exists()
    assert f"Output: {expected_output}" in result.output


def test_prepare_force_overwrite(tmp_path: Path) -> None:
    """Create output first, run with --force, verify success and file overwritten."""
    input_pdf = _copy_fixture("sample.pdf", tmp_path)
    output_pdf = tmp_path / "out.pdf"

    # Pre-create the output file
    output_pdf.write_bytes(b"placeholder")

    # Without --force should fail
    result_no_force = runner.invoke(app, [str(input_pdf), "-o", str(output_pdf)])
    assert result_no_force.exit_code != 0

    # With --force should succeed
    result = runner.invoke(app, [str(input_pdf), "-o", str(output_pdf), "--force"])
    assert result.exit_code == 0, result.output
    assert output_pdf.read_bytes().startswith(b"%PDF"), "Output should be a valid PDF"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_prepare_no_match(tmp_path: Path) -> None:
    """Run with no-match.pdf, expect exit code 1, stderr contains 'not found'."""
    input_pdf = _copy_fixture("no-match.pdf", tmp_path)
    output_pdf = tmp_path / "out.pdf"

    result = runner.invoke(app, [str(input_pdf), "-o", str(output_pdf)])

    assert result.exit_code == 1
    # CliRunner merges stderr into output by default; check combined output
    assert "not found" in result.output.lower()


def test_prepare_invalid_pdf(tmp_path: Path) -> None:
    """Run with a non-PDF file, expect exit code 2."""
    non_pdf = tmp_path / "fake.pdf"
    non_pdf.write_bytes(b"this is definitely not a pdf file")

    result = runner.invoke(app, [str(non_pdf)])

    assert result.exit_code == 2
