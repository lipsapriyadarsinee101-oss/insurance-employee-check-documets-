"""Reproducible checks of the three authored demo scenarios, not real-world accuracy."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import time

from app.claims.checks import RULES_VERSION, run_checks
from app.claims.extraction import parse_pdf
from app.claims.samples import sample_files

EXPECTED = {
    'clean': ['consistent'] * 5,
    'conflicting': ['conflict', 'conflict', 'conflict', 'consistent', 'conflict'],
    'missing': ['unknown'] * 5,
}


def evaluate():
    rows = []
    for name, expected in EXPECTED.items():
        started = time.perf_counter()
        files = sample_files(name)
        docs = [parse_pdf(role, files[role][0], files[role][1]) if role in files else parse_pdf(role, '', None)
                for role in ('policy', 'claim', 'invoice')]
        findings = run_checks(docs)
        actual = [finding.status for finding in findings]
        failures = [{'check': findings[i].code, 'expected': want, 'actual': actual[i]}
                    for i, want in enumerate(expected) if actual[i] != want]
        rows.append({'case': name, 'fictional': True, 'expected': expected, 'actual': actual,
                     'passed': not failures, 'failures': failures,
                     'pdf_sha256': {d.role: d.sha256 for d in docs},
                     'latency_ms': round((time.perf_counter() - started) * 1000, 3)})
    root = Path(__file__).resolve().parents[1]
    return {'schema_version': 1, 'rules_version': RULES_VERSION, 'python': platform.python_version(),
            'packages': {name: importlib.metadata.version(name) for name in ('pypdf', 'reportlab', 'pydantic')},
            'source_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted((root / 'app' / 'claims').glob('*.py'))},
            'mode': 'deterministic; no LLM/OCR', 'provider_calls': 0, 'api_cost': 'not applicable; no provider used',
            'limitations': 'Three authored fictional regression scenarios; not an accuracy estimate for arbitrary PDFs or insurance decisions.',
            'results': rows, 'passed': sum(row['passed'] for row in rows), 'total': len(rows)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('evaluation-results.json'))
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"{report['passed']}/{report['total']} authored scenarios matched expected findings")
    return int(report['passed'] != report['total'])


if __name__ == '__main__':
    raise SystemExit(main())
