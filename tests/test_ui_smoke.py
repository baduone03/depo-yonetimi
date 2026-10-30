"""Every Streamlit page renders without exceptions, with and without demo data."""
import pytest
from streamlit.testing.v1 import AppTest

PAGES = ["dashboard", "data_page", "analysis_page", "layout_page", "optimization_page", "routing_page",
         "simulation_page", "move_plan_page", "reports_page", "settings_page"]

SCRIPT = """
import streamlit as st
from warehouse_optimizer.ui import common as c, {page}
if {demo} and "dataset" not in st.session_state:
    c.load_demo()
{page}.render()
"""


@pytest.mark.parametrize("demo", [False, True])
@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page, demo):
    at = AppTest.from_string(SCRIPT.format(page=page, demo=demo), default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    if demo and page not in ("settings_page",):
        assert any("Sentetik" in w.value for w in at.warning)  # provenance banner is shown
