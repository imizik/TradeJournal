"""Architectural boundaries that the import graph must satisfy.

These are the rules a change cannot be allowed to break by accident, so they
are checked on the static import graph rather than left to review:

1. **Pure engine modules stay pure.** The FIFO reconstructor, parsers and
   Strategy Lab metrics are testable with no credentials, stubs or network.
   Their imports must stay inside the explicit pure-module policy below.

Each rule is an allowlist, not a denylist, so a new module is caught the first
time it is reached: the universe checked is the graph grimp builds from the
code, and the only literals are the policy lists at the top of this file.
grimp scans every ``import`` statement in a module, including ones inside
functions, so a lazy import does not slip through.

If one of these fails, the failure names the chain. Decide whether the chain is
a mistake or the policy should change; when the policy changes, change the list
here in the same commit and say so.
"""

from __future__ import annotations

import sys

import grimp
import pytest


# --- policy ------------------------------------------------------------------

# Modules with no network, no database engine and no credentials. Ordered
# roughly by how much depends on them.
PURE_MODULES = {
    "app.models",
    "app.engine.reconstructor",
    "app.engine.email_parser",
    "app.engine.behavior",
    "app.engine.analytics",  # read-only metrics over supplied journal history
    "app.engine.research",
    "app.engine.strategy_csv",
    "app.engine.strategy_metrics",
    "app.engine.strategy_lab",
    "app.engine.tradingview",
    "app.engine.tradingview_alerts",
    "app.engine.indicators",
    "app.engine.metric_reference",  # independent stdlib-only calculations
    "app.engine.metric_versions",  # identities and pure exposure direction only
    # The Isaac Market Map port and its reports. The backtest script fetches
    # the bars; these only compute on what they are handed.
    "app.engine.market_map",
    "app.engine.market_map_report",
    # The strategy factory: bars, rules, the learned filter and the gates. The
    # script reads the bar cache and the ledger; these compute on what they are
    # handed, and the gates reach data only through the loader they are given.
    "app.engine.factory_data",
    "app.engine.factory_rules",
    "app.engine.factory_model",
    "app.engine.factory_gates",
    "app.engine.factory_brief",
    # OCC symbol conversion. Pure by construction (stdlib only), and listed
    # here so it stays that way: it is imported by the vendor clients, which is
    # exactly the direction a network import would travel.
    "app.engine.occ",
    "app.engine.chart_math",  # chart-only resampling and indicator math
    "app.engine.chart_adjust",  # chart-only split adjustment of supplied bars
    "app.engine.chart_levels",  # automatic chart levels from supplied bars
    "app.engine.chart_rvol",  # chart relative volume from supplied bars and profiles
    "app.engine.symbol_info",  # summaries of supplied stored journal results
    "app.engine.symbol_info_events",  # earnings, dividend and split rows from supplied responses
    "app.engine.symbol_info_overview",  # company fundamentals from supplied Tradier responses
    "app.engine.symbol_info_news",  # headlines from supplied Alpaca and Polygon responses
    "app.engine.symbol_info_peers",  # peer tickers and chips from supplied Polygon and Tradier responses
    "app.engine.symbol_info_short",  # short interest, short volume and borrow flag from supplied responses
    "app.engine.level_alerts",  # when a level alert fires, from supplied trades and candles
    "app.engine.paper_execution",  # Practice paper fills and exits, from supplied bars and events
    # Option chain models. The Tradier adapter (options_chain) fills them; the
    # positioning engine and recorder must be able to read them without it.
    "app.engine.options_models",
    "app.engine.options_positioning",  # positioning, gamma and option levels from supplied chains
    "app.engine.options_implied",  # the at-the-money straddle from a supplied chain
}
# Third-party packages a pure module may reach. httpx, yfinance, anthropic,
# googleapiclient and grpc are deliberately absent: reaching any of them, even
# through another app module, is what "not pure" means here. pandas is present
# because it computes on data it is handed — it opens no socket and reads no
# credential.
PURE_MAY_USE = {"sqlmodel", "sqlalchemy", "pydantic", "pandas"}

# Not pure today, and worth knowing why when you touch them:
#   app.engine.trade_path  -> app.engine.alpaca   live minute-bar fetch
#   app.engine.auditor     -> app.engine.alpaca   cache/feed configuration only
# Moving those reads behind an injected loader would let them join PURE_MODULES,
# the way app.engine.indicators took a MinuteBarLoader from its caller.


# --- checks ------------------------------------------------------------------


def _is_internal(module: str) -> bool:
    return module == "app" or module.startswith("app.")


def _is_third_party(module: str) -> bool:
    return not _is_internal(module) and module.split(".")[0] not in sys.stdlib_module_names


def _chain(graph: grimp.ImportGraph, importer: str, imported: str) -> str:
    chain = graph.find_shortest_chain(importer=importer, imported=imported)
    return " -> ".join(chain) if chain else f"{importer} -> ... -> {imported}"


def impurities(graph: grimp.ImportGraph) -> dict[str, str]:
    """For each pure module, the first thing it reaches that a pure module may not."""
    found: dict[str, str] = {}
    for module in sorted(PURE_MODULES):
        for reached in sorted(graph.find_upstream_modules(module)):
            allowed = (
                reached in PURE_MODULES
                if _is_internal(reached)
                else not _is_third_party(reached) or reached in PURE_MAY_USE
            )
            if not allowed:
                found[module] = _chain(graph, module, reached)
                break
    return found


def _report(title: str, violations: dict[str, str]) -> str:
    lines = [title, ""]
    lines += [f"  {chain}" for chain in violations.values()]
    lines += ["", "Fix the import, or change the policy at the top of this test and say so."]
    return "\n".join(lines)


# --- the real graph ---------------------------------------------------------


@pytest.fixture(scope="module")
def graph() -> grimp.ImportGraph:
    # No cache: the graph must describe the checkout being tested, not a
    # previous one.
    return grimp.build_graph("app", include_external_packages=True, cache_dir=None)


def test_the_policy_names_modules_that_exist(graph: grimp.ImportGraph) -> None:
    named = PURE_MODULES
    missing = sorted(named - set(graph.modules))
    assert not missing, f"policy names modules that do not exist: {missing}"


def test_pure_engine_modules_stay_pure(graph: grimp.ImportGraph) -> None:
    found = impurities(graph)
    assert not found, _report(
        "A pure module reaches the network, the database engine or another "
        "impure module:",
        found,
    )


# --- the checks themselves catch what they claim to --------------------------
#
# A boundary test that passes on a clean graph proves nothing about whether it
# would fail on a dirty one. Each planted defect below is the smallest graph
# that violates one rule, and the check must name the chain.


def _graph(*edges: tuple[str, str]) -> grimp.ImportGraph:
    graph = grimp.ImportGraph()
    for module in PURE_MODULES | {"app.database", "httpx", "app.main"}:
        graph.add_module(module, is_squashed=not _is_internal(module))
    for importer, imported in edges:
        graph.add_import(importer=importer, imported=imported)
    return graph


def test_a_pure_module_reaching_httpx_through_another_module_is_named() -> None:
    graph = _graph(
        ("app.engine.strategy_lab", "app.engine.strategy_metrics"),
        ("app.engine.strategy_metrics", "httpx"),
    )
    assert impurities(graph) == {
        "app.engine.strategy_lab": "app.engine.strategy_lab -> app.engine.strategy_metrics -> httpx",
        "app.engine.strategy_metrics": "app.engine.strategy_metrics -> httpx",
    }


def test_a_pure_module_importing_the_database_engine_is_named() -> None:
    graph = _graph(("app.engine.reconstructor", "app.database"))
    assert impurities(graph) == {
        "app.engine.reconstructor": "app.engine.reconstructor -> app.database"
    }


def test_a_clean_graph_reports_nothing() -> None:
    graph = _graph(("app.engine.strategy_lab", "app.engine.strategy_metrics"))
    assert impurities(graph) == {}
