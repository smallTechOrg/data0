"""Pandas eval sandbox for `execute_action`.

The agent's single "tool" is eval/exec of a pandas expression the model emits as
text. This module builds the fixed namespace that expression runs in and the safe
`eval_expression` helper that captures the result, any chart, and any error.

Per `spec/agent.md` -> "## Tools & Tool Calling":
- Namespace: `df` (first DataFrame), `df1`/`df2`/... per dataset (ordered by
  `dataset_ids`), a `<filename_stem>` alias per dataset, plus the libraries
  `pd, np, plt, sns, scipy, stats, sklearn, sm`, plus `save_dataset` and `echart`.
- No filesystem/network builtins beyond these are exposed.

Phase 4 scope: `save_dataset` is REAL — it materialises the DataFrame as a
registered DERIVED dataset (CSV + Parquet + a `datasets` row with lineage) via
`graph.derived.register_derived_dataset` (C25). The module-level `save_dataset`
here is a thin best-effort wrapper with no run/parent lineage; `nodes.execute_action`
binds a *run-aware* closure into the per-run namespace that supplies the producing
`run_id` + parent `dataset_ids` + the exact action expression as `derivation_code`.

Charts (C4): the model calls `echart(...)` to build an **ECharts `option` dict**
(`{title, tooltip, xAxis, yAxis, series, ...}`) which is REGISTERED into a per-run
accumulator (same mechanism as `save_dataset`). `nodes.execute_action` reads that
accumulator, `json.dumps`-es each option, and appends to `state["charts"]`. Chart
building is defensive — bad input raises a clear `ValueError` the loop recovers
from, and never crashes a run.
"""
from __future__ import annotations

import ast
import re
import traceback
from typing import Any

import numpy as np
import pandas as pd

# Heavier optional libs imported lazily-ish at module load so the namespace is
# complete; all are guaranteed present by pyproject.
import matplotlib

matplotlib.use("Agg")  # headless: never try to open a window in the sandbox
import matplotlib.pyplot as plt  # noqa: E402
import seaborn as sns  # noqa: E402
import scipy  # noqa: E402
from scipy import stats  # noqa: E402
import sklearn  # noqa: E402
import statsmodels.api as sm  # noqa: E402

from graph.derived import register_derived_dataset  # noqa: E402
from observability.events import get_logger  # noqa: E402

logger = get_logger("graph.sandbox")


_IDENTIFIER_RE = re.compile(r"[^0-9a-zA-Z_]")


def _safe_alias(stem: str) -> str | None:
    """Turn a filename stem into a valid python identifier alias, or None."""
    alias = _IDENTIFIER_RE.sub("_", stem).strip("_")
    if not alias or alias[0].isdigit():
        alias = f"_{alias}" if alias else ""
    return alias or None


def _extract_derivation_expr(code: str) -> str:
    """Recover the DataFrame-producing expression from the recorded action.

    For a re-runnable `derivation_code` we want the expression that PRODUCES the
    saved DataFrame, not the wrapping `save_dataset(...)` call. Two shapes:

      - inlined:   `save_dataset(df.dropna(), 'x', '')`            -> `df.dropna()`
      - assigned:  `merged = df.merge(df2, on='id')`               -> `df.merge(df2, on='id')`
                   `save_dataset(merged, 'x', '')`

    In the assigned case the first argument is a bare variable, so we resolve it
    back to its assignment's right-hand side within the action — otherwise the
    stored derivation code would just be a variable name (e.g. `merged_df`), which
    is neither informative nor re-derivable. Falls back to the raw code when it
    can't be parsed or has no `save_dataset(...)` call.
    """
    code = (code or "").strip()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    # Locate the save_dataset(...) call and its first positional argument.
    first_arg: ast.expr | None = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "save_dataset"
            and node.args
        ):
            first_arg = node.args[0]
            break
    if first_arg is None:
        return code

    # A bare variable -> resolve to the LAST assignment of that name in the block.
    if isinstance(first_arg, ast.Name):
        target = first_arg.id
        rhs: ast.expr | None = None
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == target for t in stmt.targets
            ):
                rhs = stmt.value
            elif (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id == target
                and stmt.value is not None
            ):
                rhs = stmt.value
        if rhs is not None:
            try:
                return ast.unparse(rhs).strip()
            except Exception:  # noqa: BLE001 — unparse failure -> name fallback
                pass
        return target

    # Inlined expression argument.
    try:
        return ast.unparse(first_arg).strip()
    except Exception:  # noqa: BLE001
        return code


def make_save_dataset(
    *,
    run_id: str | None,
    parent_ids: list[str],
    on_registered=None,
    on_saved=None,
):
    """Build a run-aware `save_dataset(df, name, desc)` for a single run.

    The returned callable has the model-visible signature `save_dataset(df, name,
    desc="")` but closes over the producing `run_id` and parent `dataset_ids` and
    captures the current action expression as `derivation_code` (C25). On success
    it registers a real DERIVED dataset, invokes `on_registered(new_id)` (so the
    node can collect created ids) and `on_saved(name, df)` (so the node can make
    the saved frame available as a `<name>` variable in subsequent steps), and
    returns a confirmation string. A disk/db failure is CAUGHT and returned as an
    error string — it never crashes the run.

    `derivation_code` is bound per-action via the mutable `_code` cell so the node
    can set it to the exact expression that produced `df` just before eval.
    """
    state = {"code": ""}

    def _set_code(expr: str) -> None:
        state["code"] = expr or ""

    def save_dataset(df: Any, name: str, desc: str = "") -> str:
        try:
            # Record the df-producing expression (not the whole save_dataset call)
            # so /re-derive can re-run it against current parents (C25).
            derivation_code = _extract_derivation_expr(state["code"])
            new_id = register_derived_dataset(
                df,
                name,
                desc,
                run_id=run_id,
                parent_ids=list(parent_ids or []),
                derivation_code=derivation_code,
            )
            if on_registered is not None:
                try:
                    on_registered(new_id)
                except Exception:  # noqa: BLE001 — collection is best-effort
                    pass
            # Make the saved frame referenceable as `<name>` in later steps (and,
            # via the node, later turns of this session).
            if on_saved is not None:
                try:
                    on_saved(name, df)
                except Exception:  # noqa: BLE001 — best-effort namespace inject
                    pass
            rows = int(getattr(df, "shape", (0, 0))[0])
            cols = int(getattr(df, "shape", (0, 0))[1])
            alias = _safe_alias(name) or name
            return (
                f"save_dataset('{name}'): registered derived dataset {new_id} "
                f"({rows} rows x {cols} cols). Now available as the variable "
                f"`{alias}` for the rest of this analysis and later turns of this "
                f"conversation."
            )
        except Exception as exc:  # noqa: BLE001 — recorded as a step error
            logger.warning("save_dataset_failed", run_id=run_id, error=str(exc))
            return f"save_dataset('{name}') failed: {type(exc).__name__}: {exc}"

    # Expose the per-action code setter on the callable so the node can update it.
    save_dataset.set_code = _set_code  # type: ignore[attr-defined]
    return save_dataset


def save_dataset(df: Any, name: str, desc: str = "") -> str:
    """Module-level `save_dataset` — the default bound in `build_namespace`.

    This best-effort variant registers a derived dataset WITHOUT run/parent
    lineage (no producing run is known at module scope). `nodes.execute_action`
    overrides it in the per-run namespace with a run-aware closure from
    `make_save_dataset` that supplies lineage + `derivation_code`. A failure is
    caught and returned as an error string so a model call never crashes the run.
    """
    try:
        new_id = register_derived_dataset(
            df, name, desc, run_id=None, parent_ids=[], derivation_code=""
        )
        rows = int(getattr(df, "shape", (0, 0))[0])
        cols = int(getattr(df, "shape", (0, 0))[1])
        return (
            f"save_dataset('{name}'): registered derived dataset {new_id} "
            f"({rows} rows x {cols} cols)."
        )
    except Exception as exc:  # noqa: BLE001 — recorded as a step error
        return f"save_dataset('{name}') failed: {type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------- #
# Charts (C4) — ECharts `option` dicts built by `echart(...)`
# --------------------------------------------------------------------------- #

# The chart kinds `echart(...)` knows how to build from a DataFrame.
_ECHART_KINDS = {"bar", "line", "scatter", "pie", "heatmap"}

# Tooltip `trigger` per kind: axis-based charts use 'axis'; item-based use 'item'.
_ITEM_TOOLTIP_KINDS = {"pie", "scatter"}

# Default layout: a vertical, right-side, scrollable legend (outside the plot)
# plus a grid that reserves room on the right for it. Pie has no grid — instead
# its center is shifted left so the right legend never overlaps the slices.
_DEFAULT_LEGEND = {"type": "scroll", "orient": "vertical", "right": 8, "top": "middle"}
_DEFAULT_GRID = {"left": 8, "right": 120, "top": 48, "bottom": 24, "containLabel": True}
_DEFAULT_PIE_CENTER = ["40%", "54%"]
_DEFAULT_PIE_RADIUS = "62%"


def _as_jsonable(value: Any) -> Any:
    """Coerce numpy / pandas scalars to plain JSON-serialisable Python values.

    ECharts options are `json.dumps`-ed downstream, so every value placed into an
    option must survive `json.dumps`. numpy ints/floats and NaN are the common
    offenders coming out of a DataFrame.
    """
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        f = float(value)
        return None if (f != f) else f  # NaN -> None (JSON null)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and value != value:  # python NaN
        return None
    if isinstance(value, (np.ndarray,)):
        return [_as_jsonable(v) for v in value.tolist()]
    return value


def _column_values(df: pd.DataFrame, col: str) -> list[Any]:
    """Return a JSON-safe list of values for a column (or the index when col is None)."""
    series = df[col]
    return [_as_jsonable(v) for v in series.tolist()]


def _build_echart_option(
    kind: str,
    df: pd.DataFrame | None,
    *,
    x: str | None,
    y: Any,
    series: Any,
    title: str | None,
    opts: dict[str, Any],
) -> dict[str, Any]:
    """Build a sensible ECharts `option` dict from a DataFrame for `kind`.

    Layout defaults put the legend on the RIGHT, outside the plot, so it never
    overlaps the top-centered title or the axis labels: a vertical, scrollable
    `legend:{type:'scroll',orient:'vertical',right:8,top:'middle'}` plus a
    `grid:{left:8,right:120,top:48,bottom:24,containLabel:true}` that reserves
    room for it (bar/line/scatter/heatmap). Pie has no grid — its center is
    shifted left (`["40%","54%"]`) so the right legend clears the slices. The
    title is top-centered (`{left:'center',top:6}`). Tooltip trigger is 'item'
    for pie/scatter, 'axis' otherwise. Raises ValueError on bad input.
    """
    if kind not in _ECHART_KINDS:
        raise ValueError(
            f"echart: unknown kind {kind!r}; expected one of {sorted(_ECHART_KINDS)}"
        )
    if df is None:
        raise ValueError(f"echart({kind!r}): a DataFrame `df` is required")
    if not isinstance(df, pd.DataFrame):
        raise ValueError(f"echart({kind!r}): `df` must be a pandas DataFrame")

    option: dict[str, Any] = {}
    # Title: always top-centered; only carry `text` when a title was given.
    title_opt: dict[str, Any] = {"left": "center", "top": 6}
    if title:
        title_opt["text"] = str(title)
    option["title"] = title_opt
    option["tooltip"] = {
        "trigger": "item" if kind in _ITEM_TOOLTIP_KINDS else "axis"
    }
    option["legend"] = dict(_DEFAULT_LEGEND)
    # Pie has no grid; every other kind reserves room on the right for the legend.
    if kind != "pie":
        option["grid"] = dict(_DEFAULT_GRID)

    # `series` (raw ECharts series list) takes precedence over the y= shorthand.
    if series is not None:
        if kind == "pie":
            raise ValueError("echart('pie'): use x= (labels) and y= (values), not series=")
        x_col = x
        if x_col is not None:
            if x_col not in df.columns:
                raise ValueError(f"echart: x column {x_col!r} not in DataFrame")
            option["xAxis"] = {"type": "category", "data": _column_values(df, x_col)}
            option["yAxis"] = {"type": "value"}
        if not isinstance(series, list):
            raise ValueError("echart: series= must be a list of series dicts")
        option["series"] = series
        option.update(opts)
        return option

    if kind == "pie":
        # Pie: x = labels column, y = a single values column.
        if x is None or y is None:
            raise ValueError("echart('pie'): both x= (labels) and y= (values) are required")
        if x not in df.columns:
            raise ValueError(f"echart: x column {x!r} not in DataFrame")
        if not isinstance(y, str) or y not in df.columns:
            raise ValueError(f"echart('pie'): y must be a single column name in the DataFrame")
        labels = _column_values(df, x)
        values = _column_values(df, y)
        option["series"] = [
            {
                "type": "pie",
                "radius": _DEFAULT_PIE_RADIUS,
                # Shift the pie left so the right-side legend clears the slices.
                "center": list(_DEFAULT_PIE_CENTER),
                "data": [
                    {"name": _as_jsonable(n), "value": v}
                    for n, v in zip(labels, values)
                ],
            }
        ]
        option.update(opts)
        return option

    if kind == "scatter":
        # Scatter: x and y are both value columns; each point is [x, y].
        if x is None or y is None:
            raise ValueError("echart('scatter'): both x= and y= columns are required")
        if x not in df.columns:
            raise ValueError(f"echart: x column {x!r} not in DataFrame")
        y_cols = y if isinstance(y, (list, tuple)) else [y]
        option["xAxis"] = {"type": "value", "name": str(x)}
        option["yAxis"] = {"type": "value"}
        series_list: list[dict[str, Any]] = []
        xs = _column_values(df, x)
        for yc in y_cols:
            if yc not in df.columns:
                raise ValueError(f"echart: y column {yc!r} not in DataFrame")
            ys = _column_values(df, yc)
            series_list.append(
                {
                    "name": str(yc),
                    "type": "scatter",
                    "data": [[xa, ya] for xa, ya in zip(xs, ys)],
                }
            )
        option["series"] = series_list
        option.update(opts)
        return option

    # bar / line: x = category column, y = one or more value columns.
    if x is None or y is None:
        raise ValueError(f"echart({kind!r}): both x= and y= are required")
    if x not in df.columns:
        raise ValueError(f"echart: x column {x!r} not in DataFrame")
    y_cols = y if isinstance(y, (list, tuple)) else [y]
    for yc in y_cols:
        if yc not in df.columns:
            raise ValueError(f"echart: y column {yc!r} not in DataFrame")
    option["xAxis"] = {"type": "category", "data": _column_values(df, x)}
    option["yAxis"] = {"type": "value"}
    option["series"] = [
        {"name": str(yc), "type": kind, "data": _column_values(df, yc)}
        for yc in y_cols
    ]
    option.update(opts)
    return option


def make_echart(on_chart=None):
    """Build the run-aware `echart(...)` helper bound into a run's namespace.

    The returned callable builds an ECharts `option` dict from the args, REGISTERS
    it into the per-run accumulator via `on_chart(option)` (mirrors `save_dataset`'s
    `on_registered` pattern), and RETURNS the option dict so a model can return it
    as the step's bare expression too. Bad input raises a clear `ValueError` the
    eval loop catches and reports — it never silently swallows a chart request.
    """

    def echart(
        kind: str,
        df: pd.DataFrame | None = None,
        *,
        x: str | None = None,
        y: Any = None,
        series: Any = None,
        title: str | None = None,
        option: dict[str, Any] | None = None,
        **opts: Any,
    ) -> dict[str, Any]:
        # Raw-option escape hatch: accept a full ECharts option dict. Validate it
        # has a `series` key, then MERGE IN the same right-vertical layout defaults
        # — but only for keys the caller did not set explicitly (never override).
        if option is not None:
            if not isinstance(option, dict) or "series" not in option:
                raise ValueError(
                    "echart(option=...): option must be a dict containing a 'series' key"
                )
            built = dict(option)
            # Right-vertical legend when the caller didn't supply one.
            if "legend" not in built:
                built["legend"] = dict(_DEFAULT_LEGEND)
            # Axis-based options (have an xAxis/yAxis or a grid) get the grid
            # defaults extended in — pie-style options (no axes/grid) are left
            # alone so the legend doesn't collide with a non-existent plot box.
            has_axes = "xAxis" in built or "yAxis" in built
            if has_axes or "grid" in built:
                grid = dict(built.get("grid") or {})
                if "right" not in grid:
                    grid["right"] = _DEFAULT_GRID["right"]
                if "containLabel" not in grid:
                    grid["containLabel"] = _DEFAULT_GRID["containLabel"]
                built["grid"] = grid
        else:
            built = _build_echart_option(
                kind, df, x=x, y=y, series=series, title=title, opts=opts
            )

        if on_chart is not None:
            try:
                on_chart(built)
            except Exception:  # noqa: BLE001 — registration is best-effort
                pass
        return built

    return echart


# The fixed library + helper names every eval namespace seeds. A dataset whose
# filename-alias collides with one of these is NOT aliased (the library wins), so
# the model reaches it via `df{n}` instead — mirrors `build_namespace`'s
# `alias not in ns` guard for the lazy path.
_LIBRARY_NAMES = frozenset(
    {"pd", "np", "plt", "sns", "scipy", "stats", "sklearn", "sm", "save_dataset", "echart"}
)


def _library_namespace() -> dict[str, Any]:
    """The fixed library + helper seed shared by every eval namespace.

    `save_dataset`/`echart` here are the lineage-less defaults; `nodes.execute_action`
    overrides both in the per-run namespace with run-aware closures.
    """
    return {
        "pd": pd,
        "np": np,
        "plt": plt,
        "sns": sns,
        "scipy": scipy,
        "stats": stats,
        "sklearn": sklearn,
        "sm": sm,
        "save_dataset": save_dataset,
        # Default `echart` with NO run accumulator — `nodes.execute_action`
        # overrides this with a run-aware closure that collects the built options.
        "echart": make_echart(),
    }


def build_namespace(
    dataframes: list[pd.DataFrame],
    filenames: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble an EAGER eval namespace over already-loaded frames.

    `dataframes` are ordered by `dataset_ids`. `filenames` (same order, optional)
    provide the `<filename_stem>` aliases. Used by `/re-derive` (which has the
    parent frames in hand) and the unit tests; the agent loop uses the lazy
    `build_lazy_namespace` instead (loads only referenced datasets).
    """
    ns: dict[str, Any] = _library_namespace()

    filenames = filenames or []
    for idx, frame in enumerate(dataframes):
        # df1 / df2 / ... (1-based) per dataset
        ns[f"df{idx + 1}"] = frame
        # <filename_stem> alias when we have a usable name
        if idx < len(filenames) and filenames[idx]:
            stem = filenames[idx].rsplit(".", 1)[0]
            stem = stem.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            alias = _safe_alias(stem)
            if alias and alias not in ns:
                ns[alias] = frame

    # `df` is the first DataFrame (most questions are single-dataset)
    if dataframes:
        ns["df"] = dataframes[0]

    return ns


class _LazyNamespace(dict):
    """Eval namespace that materialises a dataset's DataFrame on FIRST reference.

    The agent references datasets by name — `df`, `df1`..`dfN`, or a
    `<filename_stem>` alias — exactly as with the eager `build_namespace`. Here
    those names are NOT pre-seeded: the first time the model's expression touches
    one, `__missing__` loads that dataset (and only that dataset) via the injected
    `loader`, so a question that reads one table never loads the other twenty.

    `__missing__` fires for a bare-name `LOAD_GLOBAL` because CPython takes the
    dict-subclass slow path (`PyObject_GetItem`) for `eval`/`exec` globals when the
    mapping is a dict SUBCLASS rather than an exact dict. Library names (`pd`, …)
    and `save_dataset`/`echart` ARE seeded, so they resolve normally and never hit
    `__missing__`. An unknown name raises `KeyError` -> the interpreter reports the
    usual `NameError: name 'x' is not defined`, which the eval loop feeds back.
    """

    def __init__(self, *, name_map: dict[str, str], loader, derived_frames: dict[str, Any]):
        super().__init__()
        self._name_map = name_map  # df / df1.. / <alias> -> dataset_id
        self._loader = loader  # dataset_id -> DataFrame (caches + records the load)
        self._derived_frames = derived_frames  # <alias> -> DataFrame (save_dataset outputs)

    def __missing__(self, key: str) -> Any:
        # A save_dataset'd frame referenceable by name takes precedence — it is the
        # freshest thing the model created this run.
        derived = self._derived_frames.get(key)
        if derived is not None:
            self[key] = derived
            return derived
        dataset_id = self._name_map.get(key)
        if dataset_id is None:
            raise KeyError(key)
        frame = self._loader(dataset_id)
        # Cache under the accessed name so the rest of THIS eval reuses it without
        # re-entering __missing__ (the loader also caches by id across steps).
        self[key] = frame
        return frame


def build_lazy_namespace(
    catalog: list[dict[str, Any]],
    loader,
    derived_frames: dict[str, Any] | None = None,
) -> _LazyNamespace:
    """Assemble the LAZY eval namespace the agent loop runs each step in.

    `catalog` is the ordered list of ALL candidate datasets (`{"id", "alias", ...}`)
    — the agent picks from it by referencing a name. This builds the name→id map
    (`df`, `df1`..`dfN`, and each `<alias>` that doesn't shadow a library name) and
    returns a `_LazyNamespace` seeded with the libraries + `save_dataset`/`echart`.
    `loader(dataset_id) -> DataFrame` does the actual on-demand load (and is where
    the caller records which datasets were touched). `derived_frames` holds any
    `save_dataset` outputs, referenceable by their `<alias>`.
    """
    derived_frames = derived_frames if derived_frames is not None else {}

    name_map: dict[str, str] = {}
    for idx, entry in enumerate(catalog):
        dataset_id = entry.get("id")
        if not dataset_id:
            continue
        name_map[f"df{idx + 1}"] = dataset_id
        alias = entry.get("alias")
        if alias and alias not in _LIBRARY_NAMES and alias not in name_map:
            name_map[alias] = dataset_id
    if catalog:
        first_id = catalog[0].get("id")
        if first_id:
            name_map.setdefault("df", first_id)

    ns = _LazyNamespace(name_map=name_map, loader=loader, derived_frames=derived_frames)
    ns.update(_library_namespace())
    return ns


def _stringify(result: Any) -> str:
    """Convert an arbitrary eval result to a readable string for the transcript."""
    if result is None:
        return "None"
    # An ECharts option dict (returned by `echart(...)`) is captured separately;
    # keep the transcript line compact rather than dumping the whole option.
    if isinstance(result, dict) and "series" in result:
        return "[chart captured]"
    try:
        if isinstance(result, (pd.DataFrame, pd.Series)):
            n = len(result)
            suffix = ""
            # Cap rows before calling to_string() — huge frames would OOM before truncation.
            if isinstance(result, pd.DataFrame):
                original_ncols = len(result.columns)
                # Cap rows.
                if n > 100:
                    result = result.head(100)
                    suffix += f"\n... [{n - 100} more rows not shown]"
                # Cap columns (C8: up to ~20 cols per spec).
                if original_ncols > 20:
                    result = result.iloc[:, :20]
                    suffix += f"\n[showing 20 of {original_ncols} columns]"
                text = result.to_string()
            else:
                text = result.to_string()
            text += suffix
            if len(text) > 6000:
                text = text[:6000] + "\n... [truncated]"
            return text
    except Exception:
        pass
    text = str(result)
    if len(text) > 6000:
        text = text[:6000] + "\n... [truncated]"
    return text


def eval_expression(
    expr: str, namespace: dict[str, Any]
) -> tuple[str, list[str], bool, str | None]:
    """Evaluate `expr` in `namespace`, capturing result and error.

    Returns `(result_str, charts_json_list, is_error, error_str)`. Charts are NOT
    collected here — the model builds an ECharts `option` via `echart(...)`, which
    registers it into the run-aware accumulator `nodes.execute_action` owns; that
    node reads + `json.dumps`-es the options. So the `charts_json_list` returned
    here is always empty and kept only for signature stability.

    Tries `eval` first (expressions, the common case); on a `SyntaxError` falls
    back to `exec` (statements, e.g. multi-line assignments) and reports the value
    of a trailing `_` / last expression where possible. Any exception is caught and
    reported — execution errors are recoverable (the graph loops back to plan).
    """
    expr = (expr or "").strip()
    if not expr:
        return "", [], True, "empty expression"

    # When a run-aware `save_dataset` is bound (it carries a `.set_code` hook),
    # tell it the exact expression that is about to produce the df, so a derived
    # dataset records the right `derivation_code` (C25).
    saver = namespace.get("save_dataset")
    set_code = getattr(saver, "set_code", None)
    if callable(set_code):
        try:
            set_code(expr)
        except Exception:  # noqa: BLE001 — best-effort
            pass

    try:
        try:
            result = eval(expr, namespace)  # noqa: S307 — sandboxed, intentional
        except SyntaxError:
            # Statement(s) rather than a single expression. Parse the block and, if
            # it ends in an expression, exec everything BEFORE that and eval the
            # last expression EXACTLY ONCE. The old approach (exec the whole block,
            # then eval the last *line*) ran a side-effecting tail twice — e.g.
            # `df = ...` then `save_dataset(df, ...)` registered the derived dataset
            # two times. ast.parse re-raises on genuinely invalid code (caught below).
            tree = ast.parse(expr)
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                *head, tail = tree.body
                if head:
                    exec(  # noqa: S102 — sandboxed, intentional
                        compile(ast.Module(body=head, type_ignores=[]), "<string>", "exec"),
                        namespace,
                    )
                result = eval(  # noqa: S307 — sandboxed, intentional
                    compile(ast.Expression(tail.value), "<string>", "eval"), namespace
                )
            else:
                exec(compile(tree, "<string>", "exec"), namespace)  # noqa: S102
                result = "[executed statements; no return value]"

        # Charts are captured out-of-band via the `echart(...)` accumulator the
        # node owns; nothing to collect from the eval result here.
        return _stringify(result), [], False, None
    except Exception as exc:  # noqa: BLE001 — recoverable, recorded in transcript
        err = f"{type(exc).__name__}: {exc}"
        # One compact traceback line helps the model self-correct.
        tb = traceback.format_exc().strip().splitlines()
        if tb:
            err = f"{err}\n{tb[-1]}"
        return "", [], True, err
