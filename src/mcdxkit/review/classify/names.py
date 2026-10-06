"""Case-name classifier: regex first, then a local naive Bayes model. No network, no downloads.

Stage 1 recognizes STR/SER prefixes and AASHTO long names ('Strength I', 'Service I').
Stage 2 is a multinomial naive Bayes classifier over case-name character n-grams, trained
on a seed corpus of common naming conventions plus the engineer's completed conversions
(Context.history: which final-summary cases were selected). It abstains (value None) below
80% posterior probability and never changes a selection on its own.
"""
import math
import re
from collections import Counter, defaultdict
from typing import Iterator, Optional

from ..api import Context, ReportView, Suggestion, frozen_mapping
from ..checks._shared import limit_state

LABELS = ('strength', 'service', 'extreme', 'fatigue', 'other')
CONFIDENCE = 0.8
HISTORY_WEIGHT = 3
EVIDENCE_TOKENS = 4

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


class NameModel:
    """Multinomial naive Bayes with Laplace smoothing over weighted examples."""
    def __init__(self):
        self.counts = defaultdict(Counter)
        self.totals = Counter()
        self.docs = Counter()
        self.vocab = set()

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
        # Ties broken by the token itself, so the evidence never depends on PYTHONHASHSEED.
        for t in sorted(sorted(set(tokens)), key=lambda t: (-lift(t), t)):
            text = t.removeprefix('w:').strip()
            if lift(t) <= 0 or len(evidence) == 3:
                break
            if len(text) > 1 and not any(text in e or e in text for e in evidence):
                evidence.append(text)
        return (best if probability >= CONFIDENCE else None), probability, evidence


def model(history=None):
    """Seed model plus history examples: selected names are strength, unselected names are not."""
    fitted = NameModel().fit(SEED)
    examples = history.case_examples() if history is not None else ()
    for name, selected in examples:
        # A deliberately unselected name is evidence against strength, not for any one class.
        fitted.add(name, 'strength' if selected else 'other', HISTORY_WEIGHT)
    return fitted


class CaseNames:
    kind = 'classifier'
    id = 'case_names'
    version = '1'
    title = 'Case-name classifier'
    params = frozen_mapping({'confidence': CONFIDENCE, 'history_weight': HISTORY_WEIGHT,
                             'evidence_tokens': EVIDENCE_TOKENS, 'seed_examples': len(SEED)})

    def suggest(self, view: ReportView, ctx: Context) -> Iterator[Suggestion]:
        fitted: Optional[NameModel] = None
        history = len(ctx.history.case_examples()) if ctx.history is not None else 0
        skipped = getattr(ctx.history, 'skipped', 0) if ctx.history is not None else 0
        for case in view.cases:
            state = limit_state(case.name)
            if state:
                value, probability, evidence, stage = ('strength' if state == 'STR' else 'service'), 1.0, [state], 'regex'
            else:
                if fitted is None:
                    fitted = model(ctx.history)
                value, probability, evidence = fitted.predict(case.name or '')
                stage = 'naive-bayes'
            yield Suggestion(self.id, case.id, 'limit_state', value, round(probability, 3), tuple(evidence),
                             frozen_mapping({'stage': stage, 'seed': len(SEED),
                                             'history': history, 'history_skipped': skipped}))
