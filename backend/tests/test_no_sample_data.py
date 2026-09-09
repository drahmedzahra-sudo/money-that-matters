from pathlib import Path

def test_no_sample_or_demo_python_modules():
    root=Path(__file__).parents[1]
    offenders=[p for p in root.rglob('*.py') if p.name.lower() in {'sample_data.py','demo_data.py'}]
    assert not offenders, f'Forbidden sample/demo modules found: {offenders}'
