"""Écran de dépôt : normalisation des paliers de quantité saisis (issue #60)."""

from __future__ import annotations

import pytest

from generateur_devis.ui.app import parser_quantites


@pytest.mark.parametrize(
    ("saisie", "attendu"),
    [
        ("10, 1, 10", [1, 10]),
        ("1000, 100, 10, 1", [1, 10, 100, 1000]),
        ("10,,20", [10, 20]),
        ("10, 20,", [10, 20]),
        ("5,5,5", [5]),
        (" 10 ", [10]),
        ("1, 10, 100, 1000", [1, 10, 100, 1000]),
    ],
)
def test_parser_quantites_normalise(saisie, attendu):
    assert parser_quantites(saisie) == attendu


@pytest.mark.parametrize("saisie", ["", " , ", "0", "-3", "1.5", "a", "10, 0", "10, a"])
def test_parser_quantites_refuse(saisie):
    with pytest.raises(ValueError):
        parser_quantites(saisie)
