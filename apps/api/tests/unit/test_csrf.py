import pytest

from investment_tracker.auth.dependencies import require_csrf_header
from investment_tracker.auth.errors import CsrfHeaderRequiredError


async def test_the_expected_csrf_header_passes() -> None:
    await require_csrf_header("investment-tracker")


@pytest.mark.parametrize("value", [None, "", "XMLHttpRequest", "Investment-Tracker"])
async def test_a_missing_or_wrong_csrf_header_is_rejected(value: str | None) -> None:
    with pytest.raises(CsrfHeaderRequiredError) as raised:
        await require_csrf_header(value)

    assert raised.value.status == 403
    assert raised.value.code == "CSRF_HEADER_REQUIRED"
