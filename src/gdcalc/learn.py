"""Local machine learning for load-case review: no network, no model downloads.

Two advisory models, both explainable and both unable to change inputs on their own:

* A multinomial naive Bayes classifier over case-name character n-grams. It starts from a
  seed corpus of common naming conventions and keeps learning from the engineer's own
  completed conversions: every audit records which final-summary cases were selected.
* A robust outlier detector (median/MAD modified z-scores on log magnitudes) that flags
  cases whose loads disagree with the rest of the report, including the 12x and 1000x
  signatures of kip-ft/kip-in or lb/kip mix-ups.
"""
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import engine, group_report

LABELS = ('strength', 'service', 'extreme', 'fatigue', 'other')
COMPONENTS = ('P', 'Vy', 'Vz', 'My', 'Mz')
CONFIDENCE = 0.8
HISTORY_WEIGHT = 3
EVIDENCE_TOKENS = 4
MAD_FLOOR = 0.1

# Seed corpus: AASHTO LRFD limit-state names and common abbreviations seen in GROUP input.
_ROMAN = ['I', 'II', 'III', 'IV', 'V', 'IA', 'IB']
SEED = (
    [(f'{p}{s}{n}', 'strength') for p in ('STRENGTH', 'Strength', 'STR', 'Str', 'ST') for s in (' ', '-', '_', '')
     for n in _ROMAN] +
    [(n, 'strength') for n in ('ULS', 'ULS-1', 'Factored', 'FACTORED LOADS', 'LRFD STR', 'Str1', 'STR1', 'STR 2',
                               'Ultimate', 'ULT', 'ULT-1', 'Strength Max DC', 'Strength Min DC', '1.25DC+1.75LL')] +
    [(f'{p}{s}{n}', 'service') for p in ('SERVICE', 'Service', 'SER', 'Ser', 'SRV', 'SV') for s in (' ', '-', '_', '')
     for n in _ROMAN[:4]] +
    [(n, 'service') for n in ('SLS', 'SLS-1', 'Unfactored', 'UNFACTORED', 'Working', 'WORKING LOADS', 'Ser1',
                              'SER1', 'Serviceability', 'DL+LL', 'Service Max', 'SERV')] +
    [(f'{p}{s}{n}', 'extreme') for p in ('EXTREME EVENT', 'Extreme Event', 'EXTREME', 'EXT', 'EE', 'Ext')
     for s in (' ', '-', '') for n in ('I', 'II')] +
    [(n, 'extreme') for n in ('Seismic', 'SEISMIC', 'EQ', 'Earthquake', 'Vessel Collision', 'CV', 'Ice', 'Scour Event')] +
    [(f'{p}{s}{n}', 'fatigue') for p in ('FATIGUE', 'Fatigue', 'FAT', 'Fat') for s in (' ', '-', '') for n in ('I', 'II')] +
    [(n, 'other') for n in ('Dead Load', 'DEAD', 'DL', 'DC', 'DW', 'Live Load', 'LL', 'Wind', 'WS', 'WL', 'Temperature',
                            'TU', 'Braking', 'BR', 'Construction', 'CONSTRUCTION STAGE', 'Self Weight', 'Earth Pressure',
                            'EH', 'Buoyancy', 'Settlement', 'Creep', 'Shrinkage', 'Test', 'Case')]
)


def _tokens(name):
    """Character 2-4 grams of the normalized name plus whole words; roman numerals stay distinct."""
    text = re.sub(r'[^a-z0-9+.]+', ' ', name.lower()).strip()
    words = text.split()
    padded = ' ' + text + ' '
    grams = [padded[i:i + n] for n in (2, 3, 4) for i in range(len(padded) - n + 1)]
    return ['w:' + w for w in words] + grams


class CaseClassifier:
    """Multinomial naive Bayes with Laplace smoothing over weighted examples."""
    def __init__(self):
        self.counts = defaultdict(Counter)
        self.totals = Counter()
        self.docs = Counter()
        self.vocab = set()
        self.history_examples = 0

    def add(self, name, label, weight=1):
        if label not in LABELS or not name or not name.strip():
            return
        tokens = _tokens(name)
        for token in tokens:
            self.counts[label][token] += weight
        self.totals[label] += weight * len(tokens)
        self.docs[label] += weight
        self.vocab.update(tokens)

    def fit(self, examples, weight=1):
        for name, label in examples:
            self.add(name, label, weight)
        return self

    def predict(self, name):
        """Return (label, probability, top evidence tokens); label is None below CONFIDENCE."""
        tokens = [t for t in _tokens(name or '') if t in self.vocab]
        if not tokens:
            return None, 0.0, []
        documents = sum(self.docs.values())
        size = len(self.vocab)
        scores = {}
        for label in LABELS:
            if not self.docs[label]:
                continue
            denominator = self.totals[label] + size
            # n-grams overlap heavily, so average token evidence (scaled to EVIDENCE_TOKENS
            # independent observations) instead of summing; this keeps probabilities calibrated.
            scores[label] = math.log(self.docs[label] / documents) + EVIDENCE_TOKENS * sum(
                math.log((self.counts[label][t] + 1) / denominator) for t in tokens) / len(tokens)
        peak = max(scores.values())
        weights = {label: math.exp(score - peak) for label, score in scores.items()}
        best = max(weights, key=weights.get)
        probability = weights[best] / sum(weights.values())

        def lift(t):
            return math.log((self.counts[best][t] + 1) / (self.totals[best] + size)) - max(
                math.log((self.counts[o][t] + 1) / (self.totals[o] + size)) for o in scores if o != best)
        evidence = []
        for t in sorted(set(tokens), key=lift, reverse=True):
            text = t.removeprefix('w:').strip()
            if lift(t) <= 0 or len(evidence) == 3:
                break
            if len(text) > 1 and not any(text in e or e in text for e in evidence):
                evidence.append(text)
        return (best if probability >= CONFIDENCE else None), probability, evidence


def history_examples(output_dir, limit=500):
    """Labelled names from completed gdcalc audits: selected cases are strength, others are not."""
    examples = []
    root = Path(output_dir)
    if not root.is_dir():
        return examples
    audits = sorted(root.rglob('*.audit.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    for path in audits:
        try:
            if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
                continue
            audit = json.loads(path.read_text(encoding='utf-8'))
            selected = {str(i) for i in audit['cases']}
            # case_names lists every final-summary case (audits from gdcalc 0.2.0 and earlier
            # only record the selected ones, which still teach the strength class).
            names = audit.get('case_names') or {str(c['id']): c.get('name') for c in audit['source_cases']}
            for ident, name in names.items():
                if isinstance(name, str):
                    examples.append((name, 'strength' if ident in selected else 'not-selected'))
        except (ValueError, KeyError, TypeError, OSError):
            continue
    return examples


def classifier(output_dir=None):
    model = CaseClassifier().fit(SEED)
    if output_dir:
        learned = history_examples(output_dir)
        for name, label in learned:
            # A deliberately unselected name is evidence against strength, not for any one class.
            model.add(name, 'strength' if label == 'strength' else 'other', HISTORY_WEIGHT)
        model.history_examples = len(learned)
    return model


def suggest_cases(report, *, load_source='effects', output_dir=None):
    """Classify every final-summary case; recommend confident strength cases. Never applied automatically."""
    _, parsed = engine._read_report(report, load_source)
    model = classifier(output_dir)
    rows = []
    for case in parsed['cases']:
        label, probability, evidence = model.predict(case['name'] or '')
        rows.append({'id': case['id'], 'name': case['name'], 'category': label or 'unknown',
                     'confidence': round(probability, 3), 'evidence': evidence})
    recommended = [r['id'] for r in rows if r['category'] == 'strength']
    issue = None
    try:
        group_report.select(parsed, recommended)
    except ValueError as exc:
        issue = str(exc)
    return {'model': 'naive-bayes', 'trained_on': {'seed': len(SEED), 'history': model.history_examples},
            'cases': rows, 'recommended_cases': recommended, 'selection_issue': issue,
            'unresolved_case_ids': [r['id'] for r in rows if r['category'] == 'unknown'],
            'anomalies': anomalies(parsed['cases'])}


def _peak(case, key):
    return max(case['pairs'][key]) if key == 'P' else max(map(abs, case['pairs'][key]))


def anomalies(cases, threshold=3.5):
    """Flag cases whose load magnitudes are outliers among this report's cases.

    Uses the Iglewicz-Hoaglin modified z-score of log10 peaks, which tolerates a few
    outliers in small samples. Needs at least five cases with nonzero values.
    """
    found = []
    for key in COMPONENTS:
        values = [(c, _peak(c, key)) for c in cases]
        logs = [(c, math.log10(v)) for c, v in values if v > 0]
        if len(logs) < 5:
            continue
        median = _median([v for _, v in logs])
        mad = _median([abs(v - median) for _, v in logs])
        # Floor the spread at 0.1 decades so tightly clustered reports only flag departures of
        # roughly 3x or more; ordinary case-to-case scatter is not an anomaly.
        mad = max(mad, MAD_FLOOR)
        for case, value in logs:
            score = 0.6745 * (value - median) / mad
            if abs(score) < threshold:
                continue
            factor = 10 ** (value - median)
            scale = next((label for target, label in ((12, 'kip-ft vs kip-in'), (1 / 12, 'kip-in vs kip-ft'),
                                                      (1000, 'lb vs kip'), (1 / 1000, 'kip vs lb'))
                          if key.startswith('M') or 'ft' not in label
                          if abs(math.log10(factor / target)) < 0.08), None)
            found.append({'case': case['id'], 'case_name': case['name'], 'component': key,
                          'value': 10 ** value, 'median': 10 ** median, 'ratio': round(factor, 3),
                          'score': round(score, 2), 'possible_unit_error': scale})
    return sorted(found, key=lambda a: -abs(a['score']))


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def main(argv=None, prog='gdcalc learn'):
    import argparse
    import sys
    parser = argparse.ArgumentParser(prog=prog, description='Local ML: classify load cases and flag load outliers. '
                                     'Runs offline and learns from completed conversions in --history.')
    parser.add_argument('input', type=Path, help='GROUP .gp11t or text report')
    parser.add_argument('--history', type=Path, help='Output directory of earlier conversions to learn naming from')
    parser.add_argument('--load-source', choices=['effects', 'reactions'], default='effects')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(suggest_cases(args.input, load_source=args.load_source, output_dir=args.history), indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print('gdcalc: ' + str(exc), file=sys.stderr)
        return 2
