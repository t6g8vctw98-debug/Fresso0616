"""
Tests for the shopping-list unit-reconciliation algorithm.

Covers:
  • _unit_dimension / _to_base_amount / _format_base_amount unit helpers
  • _ingredient_density (trusted-only, None when unknown)
  • _aggregate_ingredients_for_list merging across recipes:
      - same unit, same dimension (g + kg -> single kg line)
      - mixed mass+volume of a KNOWN-density ingredient (cup flour + g flour)
      - mixed dimensions of an UNKNOWN-density ingredient stay separate
      - non-convertible / textual quantities ("to taste") never auto-convert
  • SAFETY: aggregation never mutates the recipes' stored Ingredient rows.

Run from the backend/ directory:
    pytest tests/test_unit_merge.py -v
"""
import os
import sys
import tempfile
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmpdir = tempfile.mkdtemp()
_dbfile = os.path.join(_tmpdir, "test_unit_merge.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_dbfile}"
os.environ.setdefault("SECRET_KEY", "test-secret")

import backend  # noqa: E402

db = backend.db
app = backend.app


# ── pure-helper tests (no DB) ────────────────────────────────────────────────
@pytest.mark.parametrize("unit,dim", [
    ("g", "mass"), ("kg", "mass"), ("oz", "mass"),
    ("ml", "volume"), ("cup", "volume"), ("tbsp", "volume"),
    ("pcs", "count"), ("piece", "count"), ("whole", "count"),
    ("", None), ("to taste", None), ("pinch", None),
])
def test_unit_dimension(unit, dim):
    assert backend._unit_dimension(unit) == dim


def test_to_base_amount():
    assert backend._to_base_amount(1, "kg") == (1000.0, "mass")
    assert backend._to_base_amount(100, "g") == (100.0, "mass")
    assert backend._to_base_amount(2, "cup") == (pytest.approx(473.18), "volume")
    assert backend._to_base_amount(3, "pcs") == (3.0, "count")
    assert backend._to_base_amount(1, "smidgen") is None  # unknown unit


def test_ingredient_density_trusted_only():
    assert backend._ingredient_density("flour") == 0.53
    # suffix match: "all purpose flour" -> flour density
    assert backend._ingredient_density("all purpose flour") == 0.53
    # unknown ingredient -> None (no guessed density)
    assert backend._ingredient_density("saffron") is None


def test_format_base_amount_promotes_units():
    assert backend._format_base_amount(1500, "mass") == ("1.5", "kg")
    assert backend._format_base_amount(350, "mass") == ("350", "g")
    assert backend._format_base_amount(2000, "volume") == ("2", "l")
    assert backend._format_base_amount(250, "volume") == ("250", "ml")
    assert backend._format_base_amount(3, "count") == ("3", "pcs")


# ── DB-backed aggregation tests ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def ctx():
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        user = backend.User(username="merge_tester", email="merge@test.local")
        user.set_password("x")
        user.session_token = "test-session-token-merge"
        user.session_expires = backend.utcnow() + timedelta(days=1)
        db.session.add(user)
        db.session.commit()
        yield user.id


def _make_recipe(owner_id, title, ingredients):
    """ingredients: list of (name, qty, unit). Returns recipe id."""
    with app.app_context():
        r = backend.Recipe(user_id=owner_id, title=title, servings=4)
        db.session.add(r)
        db.session.flush()
        for i, (name, qty, unit) in enumerate(ingredients):
            db.session.add(backend.Ingredient(
                recipe_id=r.id, ingredient=name, quantity=qty, unit=unit,
                originalquantity=qty, originalunit=unit, order_index=i))
        db.session.commit()
        return r.id


def _find(items, name_substr):
    return [it for it in items if name_substr.lower() in it["ingredient"].lower()]


def test_same_dimension_merge_promotes(ctx):
    """500 g + 1 kg sugar -> a single 1.5 kg line."""
    r1 = _make_recipe(ctx, "Cake A", [("sugar", "500", "g")])
    r2 = _make_recipe(ctx, "Cake B", [("sugar", "1", "kg")])
    with app.app_context():
        items = backend._aggregate_ingredients_for_list([r1, r2], ctx)
    sugar = _find(items, "sugar")
    assert len(sugar) == 1
    assert sugar[0]["quantity"] == "1.5"
    assert sugar[0]["unit"] == "kg"
    assert set(sugar[0]["sources"]) == {r1, r2}


def test_mixed_mass_volume_known_density_merges(ctx):
    """2 cup flour + 100 g flour merge via flour density into one mass line.

    2 cup = 473.18 ml * 0.53 g/ml = 250.79 g; + 100 g = 350.79 g.
    """
    r1 = _make_recipe(ctx, "Bread A", [("flour", "2", "cup")])
    r2 = _make_recipe(ctx, "Bread B", [("flour", "100", "g")])
    with app.app_context():
        items = backend._aggregate_ingredients_for_list([r1, r2], ctx)
    flour = _find(items, "flour")
    assert len(flour) == 1                      # merged, not two rows
    assert flour[0]["unit"] == "g"
    assert float(flour[0]["quantity"]) == pytest.approx(350.79, abs=0.5)


def test_mixed_dimensions_unknown_density_stay_separate(ctx):
    """Saffron has no trusted density -> a volume line and a mass line do NOT
    merge (we never guess a density that could corrupt the quantity)."""
    r1 = _make_recipe(ctx, "Paella A", [("saffron", "2", "tbsp")])
    r2 = _make_recipe(ctx, "Paella B", [("saffron", "5", "g")])
    with app.app_context():
        items = backend._aggregate_ingredients_for_list([r1, r2], ctx)
    saffron = _find(items, "saffron")
    assert len(saffron) == 2                    # kept separate, safe
    units = sorted(it["unit"] for it in saffron)
    assert units == ["g", "ml"]


def test_textual_quantity_never_converted(ctx):
    """'to taste' salt stays textual and merges only on exact unit string."""
    r1 = _make_recipe(ctx, "Soup A", [("salt", "to taste", "")])
    r2 = _make_recipe(ctx, "Soup B", [("salt", "to taste", "")])
    with app.app_context():
        items = backend._aggregate_ingredients_for_list([r1, r2], ctx)
    salt = _find(items, "salt")
    assert len(salt) == 1
    assert salt[0]["quantity"] == "to taste"
    assert set(salt[0]["sources"]) == {r1, r2}


def test_aggregation_does_not_mutate_recipe(ctx):
    """SAFETY: building a shopping list must leave the recipe's stored
    Ingredient rows (quantity + unit) untouched, so cooking/scaling are safe."""
    rid = _make_recipe(ctx, "Pancakes", [("flour", "2", "cup"), ("milk", "1", "cup")])
    # snapshot before
    with app.app_context():
        before = {
            ing.ingredient: (ing.quantity, ing.unit, ing.originalquantity, ing.originalunit)
            for ing in backend.Recipe.query.get(rid).ingredients
        }
    # run aggregation (twice, to be sure)
    with app.app_context():
        backend._aggregate_ingredients_for_list([rid], ctx)
        backend._aggregate_ingredients_for_list([rid, rid], ctx)
    # snapshot after
    with app.app_context():
        after = {
            ing.ingredient: (ing.quantity, ing.unit, ing.originalquantity, ing.originalunit)
            for ing in backend.Recipe.query.get(rid).ingredients
        }
    assert before == after
