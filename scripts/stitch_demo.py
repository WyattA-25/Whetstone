"""Stitch the demo walkthrough (<90 s) from the recorded segments plus your own screen recordings.

Put your clips in video/user/ named signup.*, checkout.*, run.* (mp4/mkv/webm/mov; any length — each is
sped up to fit its slot, at most 2.5x, then trimmed). Missing clips are skipped.
Usage: python scripts/stitch_demo.py   ->  video/whetstone_demo.mp4
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
CLIPS, USER, OUT = Path("video/clips"), Path("video/user"), Path("video/whetstone_demo.mp4")
FONT = "C\\:/Windows/Fonts/segoeuib.ttf"
# (user clip name, slot seconds, caption)
SLOTS = {"checkout": (7.5, "Enter payment details in the sandbox checkout (test card), back on the Founding plan"),
         "run": (7.5, "Estimate the cost on your own key, confirm, start the run")}
ORDER = ["00_intro", "01_card_account", "01b_signup", "02_card_plan", "03b_aws_pricing",
         "03c_aws_checkout", "checkout", "04_card_run", "run", "05_card_results", "06_results", "06b_aws",
         "06c_sales", "07_outro"]
# Seconds of page-load at the start of hosted-page clips (blank while AWS pages load)
SKIP = {"03b_aws_pricing": 5.6, "03c_aws_checkout": 2.3}
NORM = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x12110f,fps=30,format=yuv420p"


def duration(p: Path) -> float:
    out = subprocess.run([FF, "-i", str(p)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def find_user(name: str) -> Path | None:
    for ext in ("mp4", "mkv", "webm", "mov"):
        p = USER / f"{name}.{ext}"
        if p.exists():
            return p
    return None


def main() -> None:
    tmp = Path("video/_norm")
    tmp.mkdir(parents=True, exist_ok=True)
    parts, total = [], 0.0
    for key in ORDER:
        if key in SLOTS:
            src = find_user(key)
            if src is None:
                print(f"skip {key}: no video/user/{key}.*")
                continue
            slot, caption = SLOTS[key]
            speed = min(max(duration(src) / slot, 1.0), 2.5)
            vf = (f"setpts=PTS/{speed:.3f},{NORM},drawtext=fontfile='{FONT}':text='{caption}':fontcolor=white:"
                  f"fontsize=24:box=1:boxcolor=0x12110fE6:boxborderw=14:x=(w-text_w)/2:y=h-72")
            args = ["-i", str(src), "-t", f"{slot}", "-vf", vf]
        else:
            args = ["-ss", f"{SKIP.get(key, 0.25)}", "-i", str(CLIPS / f"{key}.webm"), "-vf", NORM]
        out = tmp / f"{len(parts):02d}_{key}.mp4"
        subprocess.run([FF, "-loglevel", "error", "-y", *args, "-an", "-c:v", "libx264", "-preset", "fast",
                        "-crf", "20", str(out)], check=True)
        parts.append(out)
        total += duration(out)
        print(f"{key:16s} {duration(out):5.1f}s  (total {total:5.1f}s)")
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    subprocess.run([FF, "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    str(OUT)], check=True)
    final = duration(OUT)
    print(f"\n{OUT}  {final:.1f}s  {'OK (<90s)' if final < 90 else 'TOO LONG'}")


if __name__ == "__main__":
    main()
