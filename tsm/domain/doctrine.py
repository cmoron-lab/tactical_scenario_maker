"""Propriétaire unique de la doctrine HTN (knowledge_base.json).

Un seul chemin, une seule sérialisation — trois constantes divergentes
pointaient sur ce fichier avant le refactor.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KB_PATH = Path(__file__).resolve().parents[2] / 'doctrine' / 'knowledge_base.json'


def load() -> dict[str, Any]:
    with open(KB_PATH, encoding='utf-8') as f:
        return json.load(f)


def save(kb: dict[str, Any]) -> None:
    with open(KB_PATH, 'w', encoding='utf-8') as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)
        f.write('\n')
