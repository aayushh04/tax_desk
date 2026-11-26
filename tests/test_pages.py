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
    html = " ".join(md.value for md in at.markdown)
    assert "<div class='big'>₹47,601.52</div>" in html                          # headline callout
    # the statement adds up exactly: 13,00,328.88 - 45,643.20 - 1,958.32 = 12,52,727.36
    assert "(45,643.20)" in html and "(1,958.32)" in html and "12,52,727.36" in html
    assert "<tr class='risk'><td>ITC at risk</td>" in html                    # statement risk line
    assert "Not in 2B<b>10</b>" in html and "Probable<b>5</b>" in html        # status chip counts
    assert "href='#note-2'" in html and "id='note-2'" in html                 # note reference resolves


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
    html = " ".join(md.value for md in at.markdown)
    assert "Saving with the new regime" in html and "<div class='big'>₹" in html        # verdict callout
    assert "<th class='pick'>New regime</th>" in html                                    # cheaper column picked
    assert not any("JVDPK4971F" in md.value for md in at.markdown)  # sample PAN never shown unmasked


def test_mf_page_end_to_end() -> None:
    at = AppTest.from_file("../pages/3_MF_Capital_Gains.py", default_timeout=TIMEOUT)
    at.session_state["mf_load_sample"] = True
    at.run()
    assert not at.exception and _footer_present(at)
    html = " ".join(md.value for md in at.markdown)
    assert "<tr class='less'><td>Less: exemption (first ₹1,25,000)</td><td class='ref'></td><td class='amt'>(1,25,000)</td>" in html
    at.selectbox[0].set_value("2022-23").run()
    assert not at.exception
    assert any("Older years had different rates" in w.value for w in at.warning)
