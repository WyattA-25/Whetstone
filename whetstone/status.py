"""Show a run's progress. Works the same in PowerShell, cmd, and bash.

Usage: python -m whetstone.status            (latest run)
       python -m whetstone.status <run_id>   (a specific run)
       python -m whetstone.status --all      (full log instead of the last 15 lines)
"""
import json
import sys
import time
from pathlib import Path


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    runs = sorted((p for p in Path("runs").glob("*") if (p / "state.json").exists()), key=lambda p: p.stat().st_mtime)
    if not runs:
        print("no runs yet")
        return
    run = Path("runs") / args[0] if args else runs[-1]
    st = json.loads((run / "state.json").read_text())
    log = (run / "log.txt").read_text(encoding="utf-8").splitlines() if (run / "log.txt").exists() else []
    m = st["objective"]["metric"]
    fmt = (lambda a: f"{a[m]:.1%}") if m == "success" else (lambda a: f"{a[m]:.4g}")
    b, ch = st.get("baseline"), st.get("champion")
    idle = (time.time() - (run / "log.txt").stat().st_mtime) / 60 if log else 0
    print(f"run {st['run_id']}  |  task {st['task']}  |  round {st['round_done']}/{st['rounds']}  |  "
          f"{'finished: ' + st['stopped'] if st.get('stopped') else f'last activity {idle:.0f} min ago'}")
    if b and ch:
        print(f"baseline  train {fmt(b['train'])}  val {fmt(b['val'])}")
        print(f"champion  train {fmt(ch['train'])}  val {fmt(ch['val'])}  ({ch['id']}, val checked {ch.get('val_runs', 1)}x)")
    u = st["usage"]
    print(f"spend: ours ${u['optimizer']['usd']:.4f} ({u['optimizer']['calls']} calls) | "
          f"theirs ${u['scoring']['usd']:.4f} ({u['scoring']['calls']} calls)\n")
    for line in (log if "--all" in sys.argv else log[-15:]):
        print(line[:220])


if __name__ == "__main__":
    main()
