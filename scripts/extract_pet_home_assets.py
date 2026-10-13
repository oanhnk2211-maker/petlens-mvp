from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


LOGGER = logging.getLogger("pet_home_assets")
IMAGE_SUFFIXES = {".png", ".webp", ".gif", ".jpg", ".jpeg"}
ICON_CROPS = {
    # Coordinates refer to the existing UI sprite sheet (1448x1086).
    "query": (300, 70, 570, 380),
    "profile": (1150, 390, 1448, 650),
    "history": (1170, 70, 1448, 380),
}


@dataclass(frozen=True)
class Candidate:
    path: Path
    width: int
    height: int
    has_alpha: bool
    transparent_ratio: float


def inspect_image(path: Path) -> Candidate | None:
    try:
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            alpha = rgba.getchannel("A")
            extrema = alpha.getextrema()
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            histogram = alpha.histogram()
            transparent = histogram[0]
            total = rgba.width * rgba.height
            return Candidate(path, rgba.width, rgba.height, has_alpha and extrema[0] < 255, transparent / total)
    except (OSError, ValueError) as exc:
        LOGGER.warning("跳过无法读取的图片 %s：%s", path, exc)
        return None


def choose_sprite_sheet(source_dir: Path, output: Path) -> Path:
    paths = sorted(
        path for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and path.resolve() != output.resolve()
    )
    candidates = [candidate for path in paths if (candidate := inspect_image(path)) is not None]
    if not candidates:
        raise FileNotFoundError(f"在 {source_dir} 下没有找到可读取的图片")

    for item in candidates:
        LOGGER.info(
            "候选图片：%s，尺寸=%sx%s，透明通道=%s，完全透明占比=%.1f%%",
            item.path,
            item.width,
            item.height,
            "是" if item.has_alpha else "否",
            item.transparent_ratio * 100,
        )

    alpha_candidates = [item for item in candidates if item.has_alpha]
    pool = alpha_candidates or candidates
    # Generic filenames do not identify content. A sprite sheet normally has a large
    # transparent canvas, so prefer the image with the most transparent background.
    selected = max(pool, key=lambda item: (item.transparent_ratio, item.width * item.height, str(item.path)))
    LOGGER.info("无法仅凭文件名可靠判断；已扫描全部图片并选择：%s", selected.path)
    return selected.path


def _active_column_runs(alpha: Image.Image, threshold: int = 8) -> list[tuple[int, int]]:
    active = []
    pixels = alpha.load()
    for x in range(alpha.width):
        active.append(any(pixels[x, y] > threshold for y in range(alpha.height)))

    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_active in enumerate(active + [False]):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            runs.append((start, index))
            start = None
    return runs


def extract_first_top_left_sprite(source: Path, output: Path, padding: int = 12) -> None:
    with Image.open(source) as image:
        rgba = image.convert("RGBA")
        quadrant = rgba.crop((0, 0, max(1, rgba.width // 2), max(1, rgba.height // 2)))
        alpha = quadrant.getchannel("A")
        if alpha.getbbox() is None:
            raise ValueError("左上四分之一区域没有可见像素")

        runs = _active_column_runs(alpha)
        significant = [run for run in runs if run[1] - run[0] >= max(8, quadrant.width // 20)]
        if significant:
            first_start, first_end = significant[0]
            quadrant = quadrant.crop((first_start, 0, first_end, quadrant.height))
            alpha = quadrant.getchannel("A")

        # Ignore near-transparent generation noise when determining the tight box;
        # the original RGBA pixels inside that box are preserved unchanged.
        visible_alpha = alpha.point(lambda value: 255 if value > 8 else 0)
        bbox = visible_alpha.getbbox()
        if bbox is None:
            raise ValueError("未能从左上四分之一区域确定猫形象边界")
        sprite = quadrant.crop(bbox)
        padded = Image.new(
            "RGBA",
            (sprite.width + padding * 2, sprite.height + padding * 2),
            (0, 0, 0, 0),
        )
        padded.paste(sprite, (padding, padding), sprite)
        output.parent.mkdir(parents=True, exist_ok=True)
        padded.save(output, "PNG", optimize=True)
        LOGGER.info("已输出首页猫素材：%s（%sx%s）", output, padded.width, padded.height)


def _trim_with_padding(image: Image.Image, padding: int) -> Image.Image:
    alpha = image.getchannel("A")
    visible_alpha = alpha.point(lambda value: 255 if value > 8 else 0)
    bbox = visible_alpha.getbbox()
    if bbox is None:
        raise ValueError("图标裁切区域没有可见像素")
    sprite = image.crop(bbox)
    padded = Image.new(
        "RGBA",
        (sprite.width + padding * 2, sprite.height + padding * 2),
        (0, 0, 0, 0),
    )
    padded.paste(sprite, (padding, padding), sprite)
    return padded


def extract_home_icons(source: Path, output_dir: Path, padding: int = 8) -> None:
    """Extract the three small home-entry icons from the existing UI sprite sheet."""
    with Image.open(source) as image:
        rgba = image.convert("RGBA")
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, box in ICON_CROPS.items():
            icon = _trim_with_padding(rgba.crop(box), padding)
            output = output_dir / f"{name}.png"
            icon.save(output, "PNG", optimize=True)
            LOGGER.info("已输出首页图标 %s：%s（%sx%s）", name, output, icon.width, icon.height)


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    default_source = project_root / "assets" / "pet_home"
    fallback_source = Path(r"D:\petlens-mvp\assets\pet_home")
    if not default_source.exists() and fallback_source.exists():
        default_source = fallback_source

    parser = argparse.ArgumentParser(description="从 PetLens sprite sheet 提取首页白色像素猫。")
    parser.add_argument("--source-dir", type=Path, default=default_source, help="素材图片目录")
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "assets" / "pet_home" / "cats" / "home_cat.png",
        help="提取后的 PNG 路径",
    )
    parser.add_argument("--padding", type=int, default=12, help="四周透明留白像素")
    parser.add_argument("--icons-from", type=Path, help="现有 UI sprite sheet，用于提取首页三个图标")
    parser.add_argument(
        "--icons-output-dir",
        type=Path,
        default=project_root / "assets" / "pet_home" / "icons",
        help="首页图标输出目录",
    )
    parser.add_argument("--icon-padding", type=int, default=8, help="图标四周透明留白像素")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    if args.padding < 0:
        raise ValueError("padding 不能小于 0")
    source = choose_sprite_sheet(args.source_dir.resolve(), args.output.resolve())
    extract_first_top_left_sprite(source, args.output.resolve(), args.padding)
    if args.icons_from:
        if args.icon_padding < 0:
            raise ValueError("icon-padding 不能小于 0")
        extract_home_icons(args.icons_from.resolve(), args.icons_output_dir.resolve(), args.icon_padding)


if __name__ == "__main__":
    main()
