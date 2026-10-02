from modernizer.validation.validator import validate_python


def test_validator_applies_safe_ruff_import_fixes() -> None:
    source_code = (
        "from decimal import Decimal, ROUND_DOWN\n\n"
        "def quantize(value: Decimal) -> Decimal:\n"
        "    return value.quantize(Decimal('0.01'), rounding=ROUND_DOWN)\n"
    )

    result = validate_python(source_code)

    assert result["valid"] is True
    assert result["normalized_code"] != source_code
    assert "from decimal import ROUND_DOWN, Decimal" in result["normalized_code"]


def test_validator_keeps_non_fixable_lint_errors() -> None:
    result = validate_python(
        "def broken():\n"
        "    try:\n"
        "        raise ValueError()\n"
        "    except Exception:\n"
        "        pass\n"
    )

    assert result["valid"] is False
    assert result["issues"]