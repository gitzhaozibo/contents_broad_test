"""Generate test content for the portal (PDF manuals, demo videos, notes).

Creates realistic dummy files under the content root used by dummy-mode
storage (STORAGE_MODE=dummy):

    manuals/         multi-page PDF manuals (rendered with Pillow)
    videos/          short MP4 demo clips (rendered frames piped to ffmpeg)
    release_notes/   release note .txt files (shown on the announce tab)
    announcements/   announcement .txt files

Usage:
    python scripts/generate_test_data.py                 # -> $CONTENT_ROOT or <repo>/portal-content
    python scripts/generate_test_data.py --out DIR       # explicit output dir
    python scripts/generate_test_data.py --skip-videos   # without ffmpeg

Requires Pillow. Videos additionally require ffmpeg on PATH (skipped with a
warning when unavailable).
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PAGE_SIZE = (1240, 1754)  # A4 @150dpi
VIDEO_SIZE = (640, 360)
VIDEO_FPS = 12
VIDEO_SECONDS = 5

WINDOWS_FONTS = ["meiryo.ttc", "YuGothM.ttc", "msgothic.ttc"]


def find_font(size: int) -> ImageFont.ImageFont:
    """Return a Japanese-capable font when available, else the PIL default."""
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in WINDOWS_FONTS:
        path = font_dir / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


# --------------------------------------------------------------------------
# PDF manuals
# --------------------------------------------------------------------------
MANUALS = {
    "portal_user_guide.pdf": (
        "社内ポータル利用マニュアル",
        [
            "1. はじめに\n本マニュアルは社内ポータルの基本操作を説明します。\n動画・PDF・お知らせの閲覧方法を確認してください。",
            "2. コンテンツの閲覧\nホームタブから動画とマニュアルを閲覧できます。\nコンテンツはBlob Storageから配信されます。",
            "3. お問い合わせ\n不明点は情報システム部までご連絡ください。",
        ],
    ),
    "admin_operations.pdf": (
        "管理者向け運用マニュアル",
        [
            "1. 管理タブ\nFileAdminロールを持つユーザーのみ管理タブが表示されます。",
            "2. アップロードと削除\nドラッグ＆ドロップでアップロード、チェックボックスで一括削除できます。",
        ],
    ),
    "troubleshooting.pdf": (
        "トラブルシューティングガイド",
        [
            "1. 画面が表示されない場合\nブラウザキャッシュを削除して再読み込みしてください。",
            "2. アップロードに失敗する場合\nファイルサイズ上限（2GB）を確認してください。",
        ],
    ),
}


def render_page(title: str, body: str, page_no: int, total: int) -> Image.Image:
    img = Image.new("RGB", PAGE_SIZE, "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, PAGE_SIZE[0], 160], fill="#0a5b8a")
    draw.text((60, 50), title, font=find_font(48), fill="white")
    draw.multiline_text((80, 260), body, font=find_font(36), fill="#222222", spacing=18)
    draw.text((PAGE_SIZE[0] // 2 - 40, PAGE_SIZE[1] - 90), f"{page_no} / {total}", font=find_font(28), fill="#888888")
    return img


def generate_pdfs(root: Path) -> None:
    out_dir = root / "manuals"
    out_dir.mkdir(parents=True, exist_ok=True)
    for filename, (title, pages) in MANUALS.items():
        images = [render_page(title, body, i + 1, len(pages)) for i, body in enumerate(pages)]
        target = out_dir / filename
        images[0].save(target, format="PDF", save_all=True, append_images=images[1:])
        print(f"  PDF   {target}")


# --------------------------------------------------------------------------
# Demo videos
# --------------------------------------------------------------------------
VIDEOS = {
    "portal_introduction.mp4": "社内ポータルのご紹介",
    "upload_howto.mp4": "ファイルアップロード手順",
}


def video_frames(caption: str):
    total = VIDEO_FPS * VIDEO_SECONDS
    font_big = find_font(40)
    font_small = find_font(22)
    for i in range(total):
        hue = int(255 * i / total)
        img = Image.new("RGB", VIDEO_SIZE, (20, 40 + hue // 3, 80 + hue // 2))
        draw = ImageDraw.Draw(img)
        draw.text((40, 130), caption, font=font_big, fill="white")
        draw.text((40, 200), f"demo footage  {i / VIDEO_FPS:.1f}s", font=font_small, fill="#cccccc")
        # simple progress bar so playback visibly advances
        draw.rectangle([40, 300, 40 + int(560 * i / total), 315], fill="#ffcc00")
        yield img.tobytes()


def generate_videos(root: Path, ffmpeg: str) -> None:
    out_dir = root / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    size = f"{VIDEO_SIZE[0]}x{VIDEO_SIZE[1]}"
    for filename, caption in VIDEOS.items():
        target = out_dir / filename
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            size,
            "-r",
            str(VIDEO_FPS),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for frame in video_frames(caption):
            proc.stdin.write(frame)
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed for {target}")
        print(f"  MP4   {target}")


# --------------------------------------------------------------------------
# Release notes / announcements
# --------------------------------------------------------------------------
def generate_notes(root: Path) -> None:
    today = date.today().isoformat()
    notes = {
        f"release_notes/{today}_v1.2.0.txt": "v1.2.0 リリースノート\n- お知らせタブを追加しました\n- アップロードの安定性を改善しました",
        "release_notes/2026-08-01_v1.1.0.txt": "v1.1.0 リリースノート\n- 管理タブに一括削除を追加しました",
        f"release_notes/update_{today}_maintenance.txt": "定期メンテナンスを実施しました。対象: 検索インデックスの再構築。",
        "release_notes/update_2026-08-15_security-patch.txt": "セキュリティパッチを適用しました。再ログインは不要です。",
        f"release_notes/news_{today}_new-portal.txt": "新しい社内ポータルが公開されました\n動画・マニュアル・お知らせを一元管理できる新ポータルの運用を開始しました。ぜひご利用ください。",
        "release_notes/news_2026-08-10_training.txt": "ポータル操作説明会のご案内\n9月中旬に管理者向けの操作説明会を開催します。詳細は追ってご連絡します。",
        "announcements/maintenance_notice.txt": "【お知らせ】9月第2土曜 2:00-5:00 にメンテナンスを実施します。",
    }
    for rel, text in notes.items():
        target = root.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"  TXT   {target}")


DEFAULT_OUT = os.environ.get("CONTENT_ROOT") or str(Path(__file__).resolve().parent.parent / "portal-content")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help="output content root (default: $CONTENT_ROOT or <repo>/portal-content)",
    )
    parser.add_argument("--skip-videos", action="store_true", help="skip MP4 generation (no ffmpeg required)")
    args = parser.parse_args()

    root = Path(args.out).resolve()
    print(f"Generating test data under {root}")
    generate_pdfs(root)
    generate_notes(root)

    if args.skip_videos:
        print("  (videos skipped)")
        return 0
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("WARNING: ffmpeg not found on PATH; videos skipped", file=sys.stderr)
        return 0
    generate_videos(root, ffmpeg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
