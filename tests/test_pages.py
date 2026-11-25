"""Headless smoke tests of every Streamlit page (no browser needed)."""

from streamlit.testing.v1 import AppTest

TIMEOUT = 60


def _footer_present(at: AppTest) -> bool:
    return any("Not tax advice" in md.value for md in at.markdown)


def test_home_page() -> None:
    at = AppTest.from_file("../Home.py", default_timeout=TIMEOUT).run()
    assert not at.exception
    assert [b.label for b in at.button].count("Load sample data") == 3
    assert _footer_present(at)


def test_gst_page_end_to_end() -> None:
    at = AppTest.from_file("../pages/1_GST_Reconciliation.py", default_timeout=TIMEOUT).run()
    assert not at.exception and _footer_present(at)
    at.segmented_control(key="gst_source").set_value("Sample data").run()
    next(b for b in at.button if b.label == "Reconcile").click().run()
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["In books, not in 2B (ITC at risk)"] == "10"
    assert values["Probable match, needs review"] == "5"


def test_gst_page_sample_flag_from_home() -> None:
    at = AppTest.from_file("../pages/1_GST_Reconciliation.py", default_timeout=TIMEOUT)
    at.session_state["gst_load_sample"] = True
    at.run()
    assert not at.exception
    assert any(b.label == "Reconcile" for b in at.button)          # sample loaded, ready to reconcile


def test_itr_page_end_to_end() -> None:
    at = AppTest.from_file("../pages/2_ITR_Regime_Comparison.py", default_timeout=TIMEOUT)
    at.session_state["itr_load_sample"] = True
    at.run()
    assert not at.exception and _footer_present(at)
    next(b for b in at.button if "Compare" in b.label).click().run()
    assert not at.exception
    assert any("New regime" in s.value and "cheaper" in s.value for s in at.success)
    assert not any("JVDPK4971F" in md.value for md in at.markdown)  # sample PAN never shown unmasked


def test_mf_page_end_to_end() -> None:
    at = AppTest.from_file("../pages/3_MF_Capital_Gains.py", default_timeout=TIMEOUT)
    at.session_state["mf_load_sample"] = True
    at.run()
    assert not at.exception and _footer_present(at)
    values = {m.label: m.value for m in at.metric}
    assert values["LTCG exemption used"] == "₹1,25,000"
    at.selectbox[0].set_value("2022-23").run()
    assert not at.exception
    assert any("Older years had different rates" in w.value for w in at.warning)
