import pymupdf4llm
import sys

def main():
    md = pymupdf4llm.to_markdown("/tmp/moodle_2_Nivel 4 - PA Aspectos Avanzados de Calidad de Software 2026.docx.pdf")
    lines = md.split("\n")
    for i, line in enumerate(lines):
        if "parcial" in line.lower() or "examen" in line.lower() or "evalua" in line.lower():
            print(f"Line {i}: {line}")

if __name__ == "__main__":
    main()
