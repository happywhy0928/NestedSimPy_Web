"""Generate a runnable Colab notebook for each official-parity example.

Each notebook installs NestedSimPy from the hosted wheel, writes a
self-contained version of the example (the `simpy_examples/<name>_nested.py`
model with the local `_imports` shim replaced by an inline prelude), runs it as
a subprocess so its outer output is clean, then reads the run back with
`OutputManager`.

Run from the docs repo root:

    python notebooks/build_colabs.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = ROOT / "simpy_examples"
NOTEBOOKS_DIR = ROOT / "notebooks"

WHEEL_DRIVE_ID = "1N7mlgDVpVids6Ekr4p2e-gEUrUodiEuq"

# The inline prelude recreates the surface of simpy_examples/_imports.py from
# the installed `nestedsimpy` package, so each example runs without the shim.
PRELUDE = '''# --- inline prelude (replaces the examples' local _imports shim) ---
import argparse, os, random, shutil, sys, itertools
from pathlib import Path

import simpy
import nestedsimpy
from nestedsimpy import (
    NestedEnvironment, NestedResource, NestedPreemptiveResource,
    NestedStore, NestedContainer,
)
try:
    from nestedsimpy.postprocess import (
        package_latest_run, relocate_raw_artifacts, export_realizations,
    )
except Exception:  # pragma: no cover
    package_latest_run = relocate_raw_artifacts = export_realizations = None

DEFAULT_OUT_ROOT = Path("nested_output")
DEFAULT_AUTOPLOT = False
REPO_ROOT = Path(".")
PACKAGE_ROOT = Path(".")

def default_out(*parts):
    p = DEFAULT_OUT_ROOT.joinpath(*map(str, parts)); p.mkdir(parents=True, exist_ok=True); return p

def set_nested_output_folder(*parts):
    p = Path(os.path.join(*[str(x) for x in parts])); p.mkdir(parents=True, exist_ok=True); return p
# --- end prelude ---

'''

EXAMPLES = {
    "bank_reneging": dict(
        title="Bank Renege", page="official-parity/bank-reneging", primitive="NestedResource",
        url="https://simpy.readthedocs.io/en/latest/examples/bank_renege.html",
        blurb="a counter with reneging customers (a `Resource` plus condition events)",
    ),
    "carwash": dict(
        title="Carwash", page="official-parity/carwash", primitive="NestedResource",
        url="https://simpy.readthedocs.io/en/latest/examples/carwash.html",
        blurb="cars sharing a bank of washing machines (a `Resource`)",
    ),
    "event_latency": dict(
        title="Event Latency", page="official-parity/event-latency", primitive="NestedStore",
        url="https://simpy.readthedocs.io/en/latest/examples/latency.html",
        blurb="a delayed message channel built on a `Store`",
    ),
    "gas_station": dict(
        title="Gas Station Refueling", page="official-parity/gas-station",
        primitive="NestedResource + NestedContainer",
        url="https://simpy.readthedocs.io/en/latest/examples/gas_station_refuel.html",
        blurb="cars refuelling from a shared tank (a `Resource` and a `Container`)",
    ),
    "machine_shop": dict(
        title="Machine Shop", page="official-parity/machine-shop", primitive="NestedPreemptiveResource",
        url="https://simpy.readthedocs.io/en/latest/examples/machine_shop.html",
        blurb="machines that break down and a repairman (a `PreemptiveResource`)",
    ),
    "movie_reneging": dict(
        title="Movie Renege", page="official-parity/movie-reneging", primitive="NestedResource",
        url="https://simpy.readthedocs.io/en/latest/examples/movie_renege.html",
        blurb="moviegoers queueing for tickets and leaving when a film sells out",
    ),
    "process_communication": dict(
        title="Process Communication", page="official-parity/process-communication", primitive="NestedStore",
        url="https://simpy.readthedocs.io/en/latest/examples/process_communication.html",
        blurb="producer/consumer processes talking over a `Store`",
    ),
    "dual_sourcing": dict(
        title="Dual Sourcing with Lookahead Expediting", page="official-parity/dual-sourcing",
        primitive="env.decide + set_inner_actions",
        url=None,
        blurb="the dual-sourcing inventory model of Song, Xiao, Zhang and "
              "Zipkin (2017), where lead times are endogenous and in each "
              "decision epoch the decision-maker decides whether to place a "
              "normal or an expedited order",
        inspect_rollout=True,
    ),
    "inventory_lookahead": dict(
        title="Inventory with Lookahead Decisions", page="topical-guides/lookahead-actions",
        primitive="env.decide + set_inner_actions",
        url=None,
        blurb="a periodic-review stock whose order decision is chosen by trying each "
              "candidate quantity in inner simulations",
        inspect_rollout=True,
    ),
}


def deshim(name: str) -> str:
    """Return the example model with the `_imports` shim removed."""

    text = (EXAMPLES_DIR / f"{name}_nested.py").read_text(encoding="utf-8")
    out = []
    for line in text.splitlines():
        if line.strip().startswith("from _imports import *"):
            continue
        # process_communication pulls wait_time_hook from a local tools module;
        # use the packaged one instead.
        line = line.replace(
            "from tools.postprocess_helpers import wait_time_hook",
            "from nestedsimpy.reporting import wait_time_hook",
        )
        out.append(line)
    return "\n".join(out) + "\n"


def md(*lines):
    return {"cell_type": "markdown", "metadata": {}, "source": _src(lines)}


def code(*lines):
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": _src(lines)}


def _src(lines):
    text = "\n".join(lines)
    parts = text.splitlines(keepends=True)
    return parts if parts else [text]


def build(name: str, meta: dict) -> dict:
    model = deshim(name)
    # `from __future__` imports must stay at the very top of the file, ahead of
    # the prelude.
    future = [l for l in model.splitlines() if l.startswith("from __future__")]
    model = "\n".join(l for l in model.splitlines() if not l.startswith("from __future__")) + "\n"
    future_block = ("".join(l + "\n" for l in future) + "\n") if future else ""
    script = f"{name}_colab.py"
    out_glob = f"simpy_examples/{name}/**/raw"

    install = (
        "# Pre-release install from a hosted wheel (Google Drive).\n"
        "!pip install -q gdown\n"
        "import gdown\n"
        f'gdown.download(id="{WHEEL_DRIVE_ID}",\n'
        '               output="nestedsimpy-0.1.0-py3-none-any.whl", quiet=True)\n'
        '!pip install -q "nestedsimpy-0.1.0-py3-none-any.whl[plot]"\n'
        "\n"
        "import nestedsimpy\n"
        'print("NestedSimPy ready —", len(nestedsimpy.__all__), "public objects")'
    )

    writefile = f"%%writefile {script}\n" + future_block + PRELUDE + model

    run = (
        "# Run as a subprocess so the outer output is clean (inner branches run in separate processes).\n"
        f"!python {script}"
    )

    if meta.get("inspect_rollout"):
        inspect = (
            "import glob, os\n"
            "import pandas as pd\n"
            "\n"
            f'run = os.path.dirname(glob.glob("simpy_examples/{name}/**/rollout", recursive=True)[0])\n'
            "\n"
            "# Two of the four rollout CSVs: the executed picks, and every\n"
            "# candidate's score per decision.\n"
            'outer_decisions = pd.read_csv(f"{run}/rollout/outer_decisions.csv")\n'
            'aggregated = pd.read_csv(f"{run}/rollout/inner_trajectories_aggregated.csv")\n'
            'print(outer_decisions.to_string(index=False))  # base_policy pick = no override\n'
            'print()\n'
            'print(aggregated.head(8).to_string(index=False))  # base_policy row = the baseline decision, scored as one more candidate\n'
        )
    else:
        inspect = (
        "import glob, os\n"
        f'run = os.path.dirname(glob.glob("{out_glob}", recursive=True)[0])\n'
        "\n"
        "from nestedsimpy import OutputManager\n"
        "om = OutputManager(run)\n"
        'print(f"{len(om.triggers())} trigger events; '
        'the outer path has {len(om.export_outer_event_log())} recorded events")\n'
        "\n"
        'om.visualize_outer_static("outer.png")   # outer trajectory, saved as a static image\n'
        "fig = om.visualize_outer_interactive()   # the same trajectory as an interactive plot\n"
        "fig.show()\n"
        '\n'
        'om.export_outer_event_log("outer.csv")   # the outer event log as a CSV\n'
        'print("wrote outer.csv")'
        )

    if meta["url"] is None:
        intro = md(
            f"# NestedSimPy — {meta['title']}",
            "",
            f"This notebook runs a NestedSimPy-specific example: {meta['blurb']}. "
            f"It uses `env.decide` and `set_inner_actions`.",
            "",
            f"See the [example page](https://nestedsimpy.github.io/{meta['page']}.html) "
            f"for the side-by-side plain/nested code.",
        )
    else:
        intro = md(
            f"# NestedSimPy — {meta['title']}",
            "",
            f"[NestedSimPy](https://nestedsimpy.github.io/) adapts SimPy's official "
            f"[{meta['title']} example]({meta['url']}) — {meta['blurb']} — so the outer "
            f"behavior is unchanged while inner branches are launched at each trigger "
            f"event. This example uses `{meta['primitive']}`.",
            "",
            f"See the [example page](https://nestedsimpy.github.io/{meta['page']}.html) "
            f"for the side-by-side plain/nested code.",
        )
    cells = [
        intro,
        md("## 1. Install",
           "",
           "_Pre-release: NestedSimPy installs from a hosted wheel. "
           "(After the public release this becomes `pip install nestedsimpy`.)_"),
        code(install),
        md("## 2. Run the nested example",
           "",
           "The model is written to a file and run as a subprocess; the output below "
           + ("is the **outer** trajectory. In rollout mode it executes the "
              "lookahead picks, so it can differ from the plain example."
              if meta.get("inspect_rollout") else
              "is the **outer** trajectory and matches the plain SimPy example.")),
        code(writefile),
        code(run),
        md("## 3. Inspect the run",
           "",
           ("The lookahead CSVs are read back with pandas: the executed "
            "picks and the per-action score table."
            if meta.get("inspect_rollout") else
            "`OutputManager` reads the run folder and reports the trigger events, "
            "plots the outer trajectory, and exports the sample path.")),
        code(inspect),
    ]

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
            "colab": {"provenance": []},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


def main():
    for name, meta in EXAMPLES.items():
        nb = build(name, meta)
        out = NOTEBOOKS_DIR / f"NestedSimPy_{name}.ipynb"
        out.write_text(json.dumps(nb, indent=1) + "\n", encoding="utf-8")
        print("wrote", out.name)


if __name__ == "__main__":
    main()
