import classify_stop as stop
from rgia_fullscope import GUBERNIAS_ONLY, KEYWORDS, TERRITORIES


def test_canonical_rgia_scope_is_294_queries_and_small_variant_is_24():
    assert len(TERRITORIES) == 49
    assert len(KEYWORDS) == 6
    assert len(TERRITORIES) * len(KEYWORDS) == 294
    assert len(GUBERNIAS_ONLY) == 4
    assert len(GUBERNIAS_ONLY) * len(KEYWORDS) == 24


def test_rgia_profile_does_not_treat_login_form_as_a_barrier():
    html = b"<html><body><input type='password'><p>Nothing useful</p></body></html>"
    verdict = stop.classify_response(200, "text/html", html, profile=stop.RGIA)
    assert verdict["verdict"] == stop.AMBIGUOUS_EMPTY
    assert "login_form_present_ignored" in verdict["signals"]
