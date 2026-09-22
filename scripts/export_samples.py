"""Export all eight fictional PDFs for trying the upload workflow."""
import argparse
from pathlib import Path
from app.claims.samples import SAMPLE_NAMES, sample_files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('sample-pdfs'))
    args = parser.parse_args()
    for name in SAMPLE_NAMES:
        directory = args.output / name
        directory.mkdir(parents=True, exist_ok=True)
        for filename, data in sample_files(name).values():
            (directory / filename).write_bytes(data)
    print(f'Exported 8 fictional PDFs to {args.output}')


if __name__ == '__main__':
    main()
