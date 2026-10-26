#!/usr/bin/env python3
"""Assemble follow-run frame JPGs into a demo MP4 video.

    python scripts/make_demo_video.py --session pas_follow --fps 10

Reads ``logs/rec/<session>/f_*.jpg`` frame files and uses ffmpeg to stitch
them into an H.264 MP4.  If ``follow_telemetry.csv`` is present in the same
directory, prints a summary of the run statistics.
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _natural_sort_key(p: Path) -> int:
    """Extract the numeric index from filenames like f_0042.jpg."""
    m = re.search(r"(\d+)", p.stem)
    return int(m.group(1)) if m else 0


def summarise_telemetry(csv_path: Path) -> None:
    """Print a run summary from follow_telemetry.csv."""
    try:
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return

        total = len(rows)
        locked = sum(1 for r in rows if int(r.get("locked", 0)))
        ratio = 100.0 * locked / max(total, 1)
        times = [float(r["t"]) for r in rows if "t" in r]
        duration = max(times) - min(times) if len(times) >= 2 else 0.0

        errs = [abs(float(r["err_x"])) for r in rows if float(r.get("locked", 0))]
        mean_err = sum(errs) / len(errs) if errs else 0.0

        print(f"\n  📊 Telemetry Summary")
        print(f"     Duration     : {duration:.1f}s")
        print(f"     Ticks        : {total}")
        print(f"     Locked       : {locked} ({ratio:.0f}%)")
        print(f"     Mean |err_x| : {mean_err:.3f}")
        switches = int(rows[-1].get("switches", 0)) if "switches" in rows[-1] else 0
        if switches:
            print(f"     ID switches  : {switches}")
    except Exception as e:
        print(f"  (telemetry read failed: {e})")


def _render_video(frames: list, output: Path, fps: int = 10, crf: int = 22) -> bool:
    """Write a list of image paths to an MP4 via ffmpeg concat demuxer."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="garuda_frames_"
    ) as tmp:
        for frame in frames:
            tmp.write(f"file '{Path(frame).resolve()}'\n")
            tmp.write(f"duration {1.0 / fps:.6f}\n")
        tmp.write(f"file '{Path(frames[-1]).resolve()}'\n")
        concat_file = tmp.name

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", str(crf),
        "-r", str(fps),
        "-movflags", "+faststart",
        str(output),
    ]
    try:
        result = subprocess.run(
            [str(c) for c in cmd],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"❌ ffmpeg failed:\n{result.stderr[-500:]}")
            return False
    except FileNotFoundError:
        print("❌ ffmpeg not found.")
        return False
    except subprocess.TimeoutExpired:
        print("❌ ffmpeg timed out (>120s)")
        return False
    finally:
        try:
            Path(concat_file).unlink(missing_ok=True)
        except Exception:
            pass
    size_mb = Path(output).stat().st_size / (1024 * 1024)
    expected_duration = len(frames) / fps
    print(f"  ✅ Video saved: {output} ({size_mb:.1f} MB, ~{expected_duration:.1f}s)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Assemble follow-run frames into MP4")
    ap.add_argument("--session", default="pas_follow",
                     help="recording session name under logs/rec/")
    ap.add_argument("--fps", type=int, default=10,
                     help="output video framerate")
    ap.add_argument("--output", default=None,
                     help="output MP4 path (default: logs/rec/<session>/demo.mp4)")
    ap.add_argument("--crf", type=int, default=22,
                     help="H.264 CRF quality (lower = better, default 22)")
    args = ap.parse_args()

    session_dir = Path("logs/rec") / args.session
    if not session_dir.is_dir():
        # Also check if there's a nested 'follow' subdir from the voice pilot.
        alt = session_dir / "follow"
        if alt.is_dir():
            session_dir = alt
        else:
            print(f"❌ Session directory not found: {session_dir}")
            return 1

    frames = sorted(session_dir.glob("f_*.jpg"), key=_natural_sort_key)
    if not frames:
        print(f"❌ No f_*.jpg frames found in {session_dir}")
        return 1

    output = Path(args.output) if args.output else session_dir / "demo.mp4"
    print(f"  🎬 Assembling {len(frames)} frames → {output}")
    print(f"     FPS={args.fps}  CRF={args.crf}")

    # Write a temporary file list for ffmpeg's concat demuxer.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="garuda_frames_"
    ) as tmp:
        for frame in frames:
            # ffmpeg concat demuxer format: file '<path>'
            tmp.write(f"file '{frame.resolve()}'\n")
            tmp.write(f"duration {1.0 / args.fps:.6f}\n")
        # Repeat the last frame to avoid a 0-duration tail.
        tmp.write(f"file '{frames[-1].resolve()}'\n")
        concat_file = tmp.name

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", str(args.crf),
        "-r", str(args.fps),
        "-movflags", "+faststart",
        output,
    ]

    try:
        result = subprocess.run(
            [str(c) for c in cmd],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"❌ ffmpeg failed:\n{result.stderr[-500:]}")
            return 2
    except FileNotFoundError:
        print("❌ ffmpeg not found. Install: sudo apt install ffmpeg")
        return 3
    except subprocess.TimeoutExpired:
        print("❌ ffmpeg timed out (>120s)")
        return 4
    finally:
        try:
            Path(concat_file).unlink(missing_ok=True)
        except Exception:
            pass

    size_mb = output.stat().st_size / (1024 * 1024)
    expected_duration = len(frames) / args.fps
    print(f"  ✅ Video saved: {output} ({size_mb:.1f} MB, ~{expected_duration:.1f}s)")

    # Check for eagle view frames
    eagle_frames = sorted(session_dir.glob("eagle_*.jpg"), key=_natural_sort_key)
    if eagle_frames:
        eagle_output = session_dir / "demo_eagle.mp4"
        print(f"\n  🦅 Found {len(eagle_frames)} eagle view frames! Assembling eagle demo...")
        _render_video(eagle_frames, eagle_output, fps=args.fps, crf=args.crf)

    # Print telemetry summary if available.
    for candidate in [
        session_dir / "follow_telemetry.csv",
        session_dir.parent / "follow_telemetry.csv",
    ]:
        if candidate.exists():
            summarise_telemetry(candidate)
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
