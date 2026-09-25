"""Architectural boundaries that the import graph must satisfy.

These are the rules a change cannot be allowed to break by accident, so they
are checked on the static import graph rather than left to review:

1. **The public ingress reaches only its own modules.** ``app.tradingview_ingress``
   is the one process that may be exposed to the internet. Whatever it imports,
   directly or through any chain, runs in that process with that process's
   credentials. It must never pull in the private database engine
   (``app.database``), the private app or its routers, the migration runner, or
   any module that holds a private API key.

2. **The private app never imports the ingress side.** ``app.tradingview_database``
   reads ``TRADINGVIEW_DATABASE_URL``; the private app must not grow a dependency
   on it.

3. **Pure engine modules stay pure.** The FIFO reconstructor, the parsers and
   the Strategy Lab metrics are testable with no credentials, no stubs and no
   network. That property is only as durable as the imports: a pure module may
   import other pure modules, ``app.models`` and a short list of third-party
   packages, and nothing else.

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

# Everything the public ingress process may import, directly or indirectly.
INGRESS_ENTRYPOINT = "app.tradingview_ingress"
INGRESS_MAY_REACH = {
    "app.tradingview_ingress",
    "app.tradingview_database",
    "app.routers.tradingview_webhook",
    "app.engine.tradingview",
    "app.engine.tradingview_alerts",
    "app.models",
}

# Modules that belong to the ingress side only. Nothing outside this set may
# import them.
INGRESS_ONLY = {"app.tradingview_ingress", "app.tradingview_database"}

# Modules with no network, no database engine and no credentials. Ordered
# roughly by how much depends on them.
PURE_MODULES = {
    "app.models",
    "app.engine.reconstructor",
    "app.engine.email_parser",
    "app.engine.behavior",
    "app.engine.research",
    "app.engine.strategy_csv",
    "app.engine.strategy_metrics",
    "app.engine.strategy_lab",
    "app.engine.tradingview",
    "app.engine.tradingview_alerts",
    "app.engine.indicators",
    # The Isaac Market Map port and its reports. The backtest script fetches
    # the bars; these only compute on what they are handed.
    "app.engine.market_map",
    "app.engine.market_map_report",
    # OCC symbol conversion. Pure by construction (stdlib only), and listed
    # here so it stays that way: it is imported by the vendor clients, which is
    # exactly the direction a network import would travel.
    "app.engine.occ",
}
# Third-party packages a pure module may reach. httpx, yfinance, anthropic,
# googleapiclient and grpc are deliberately absent: reaching any of them, even
# through another app module, is what "not pure" means here. pandas is present
# because it computes on data it is handed — it opens no socket and reads no
# credential.
PURE_MAY_USE = {"sqlmodel", "sqlalchemy", "pydantic", "pandas"}

# Not pure today, and worth knowing why when you touch them:
#   app.engine.trade_path  -> app.engine.alpaca   live minute-bar fetch
#   app.engine.auditor     -> app.engine.alpaca   live minute-bar fetch
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


def ingress_strays(graph: grimp.ImportGraph) -> dict[str, str]:
    """Internal modules the ingress reaches that the policy does not allow, with the chain."""
    reached = graph.find_upstream_modules(INGRESS_ENTRYPOINT) | {INGRESS_ENTRYPOINT}
    strays = {m for m in reached if _is_internal(m)} - INGRESS_MAY_REACH
    return {m: _chain(graph, INGRESS_ENTRYPOINT, m) for m in sorted(strays)}


def ingress_only_leaks(graph: grimp.ImportGraph) -> dict[str, str]:
    """Modules outside the ingress side that import an ingress-only module."""
    leaks: dict[str, str] = {}
    for module in sorted(INGRESS_ONLY):
        for importer in sorted(graph.find_downstream_modules(module)):
            if importer not in INGRESS_MAY_REACH:
                leaks[importer] = _chain(graph, importer, module)
    return leaks


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
    named = INGRESS_MAY_REACH | INGRESS_ONLY | PURE_MODULES
    missing = sorted(named - set(graph.modules))
    assert not missing, f"policy names modules that do not exist: {missing}"


def test_the_public_ingress_reaches_only_its_own_modules(graph: grimp.ImportGraph) -> None:
    strays = ingress_strays(graph)
    assert not strays, _report(
        "The public ingress imports private modules. Whatever it imports runs "
        "in the exposed process with that process's credentials:",
        strays,
    )


def test_the_private_app_does_not_import_the_ingress_side(graph: grimp.ImportGraph) -> None:
    leaks = ingress_only_leaks(graph)
    assert not leaks, _report(
        "A private module imports the ingress side, which reads "
        "TRADINGVIEW_DATABASE_URL:",
        leaks,
    )


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
    for module in INGRESS_MAY_REACH | PURE_MODULES | {"app.database", "httpx", "app.main"}:
        graph.add_module(module, is_squashed=not _is_internal(module))
    for importer, imported in edges:
        graph.add_import(importer=importer, imported=imported)
    return graph


def test_a_private_import_two_hops_from_the_ingress_is_named() -> None:
    graph = _graph(
        ("app.tradingview_ingress", "app.routers.tradingview_webhook"),
        ("app.routers.tradingview_webhook", "app.engine.tradingview_alerts"),
        ("app.engine.tradingview_alerts", "app.database"),
    )
    assert ingress_strays(graph) == {
        "app.database": (
            "app.tradingview_ingress -> app.routers.tradingview_webhook -> "
            "app.engine.tradingview_alerts -> app.database"
        )
    }


def test_the_private_app_importing_the_ingress_database_is_named() -> None:
    graph = _graph(("app.main", "app.tradingview_database"))
    assert ingress_only_leaks(graph) == {"app.main": "app.main -> app.tradingview_database"}


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
    graph = _graph(
        ("app.tradingview_ingress", "app.routers.tradingview_webhook"),
        ("app.engine.strategy_lab", "app.engine.strategy_metrics"),
        ("app.engine.tradingview_alerts", "app.models"),
    )
    assert ingress_strays(graph) == {}
    assert ingress_only_leaks(graph) == {}
    assert impurities(graph) == {}
