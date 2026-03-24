#!/usr/bin/env python3
"""Generate test PDF fixtures with known text positions."""

from fpdf import FPDF
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def create_sample_pdf():
    """PDF with 'Employee Name' on page 1."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)

    pdf.set_y(30)
    pdf.cell(0, 10, text="Employment Agreement", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.cell(0, 10, text="This agreement is entered into on this date.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(20)
    pdf.cell(0, 10, text="Terms and conditions apply as outlined below.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(40)

    pdf.set_font("Helvetica", "B", size=12)
    pdf.cell(0, 10, text="Employee Name", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 10, text="Date: _______________", new_x="LMARGIN", new_y="NEXT")

    pdf.output(str(FIXTURES_DIR / "sample.pdf"))


def create_no_match_pdf():
    """PDF without 'Employee Name' text."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, text="This document has no signature line.", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 10, text="It is just a plain document.", new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(FIXTURES_DIR / "no-match.pdf"))


def create_multi_match_pdf():
    """PDF with 'Employee Name' appearing multiple times."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)

    pdf.cell(0, 10, text="Multi-Signer Agreement", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(20)

    pdf.set_font("Helvetica", "B", size=12)
    pdf.cell(0, 10, text="Employee Name", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 10, text="Date: _______________", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(30)

    pdf.set_font("Helvetica", "B", size=12)
    pdf.cell(0, 10, text="Employee Name", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 10, text="Date: _______________", new_x="LMARGIN", new_y="NEXT")

    pdf.output(str(FIXTURES_DIR / "multi-match.pdf"))


if __name__ == "__main__":
    create_sample_pdf()
    create_no_match_pdf()
    create_multi_match_pdf()
    print("Test PDFs created in", FIXTURES_DIR)
