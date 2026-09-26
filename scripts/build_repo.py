#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
REPO_DIR = ROOT / "repo"
ZIPS_DIR = REPO_DIR / "zips"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Kodi repository files and auto-bump addon versions."
    )
    parser.add_argument(
        "--addons",
        nargs="+",
        default=["plugin.video.gloriosotv", "repository.gloriosotv"],
        help="Addon directories at project root.",
    )
    parser.add_argument(
        "--bump",
        nargs="*",
        default=["plugin.video.gloriosotv"],
        help="Addons to auto-bump patch version.",
    )
    parser.add_argument(
        "--repo-url",
        default="https://raw.githubusercontent.com/glorioso-tv/glorioso-tv.github.io/main",
        help="Raw GitHub URL used in repository.gloriosotv/addon.xml.",
    )
    return parser.parse_args()


def bump_patch(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match:
        raise ValueError(f"Unsupported version format: {version}")
    major, minor, patch = map(int, match.groups())
    return f"{major}.{minor}.{patch + 1}"


def read_xml(path: Path) -> ET.ElementTree:
    return ET.parse(path)


def write_xml(path: Path, tree: ET.ElementTree) -> None:
    tree.write(path, encoding="UTF-8", xml_declaration=True)


def update_repository_urls(tree: ET.ElementTree, repo_url: str) -> None:
    root = tree.getroot()
    info = root.find("./extension/dir/info")
    checksum = root.find("./extension/dir/checksum")
    datadir = root.find("./extension/dir/datadir")
    source = root.find("./extension[@point='xbmc.addon.metadata']/source")

    if info is not None:
        info.text = f"{repo_url}/repo/addons.xml"
    if checksum is not None:
        checksum.text = f"{repo_url}/repo/addons.xml.md5"
    if datadir is not None:
        datadir.text = f"{repo_url}/repo/zips/"
    if source is not None and "CHANGE_ME" in (source.text or ""):
        source.text = repo_url.replace("raw.githubusercontent.com", "github.com").replace("/main", "")


def zip_addon(addon_dir: Path, addon_id: str, version: str) -> Path:
    target_dir = ZIPS_DIR / addon_id
    target_dir.mkdir(parents=True, exist_ok=True)
    zip_path = target_dir / f"{addon_id}-{version}.zip"

    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zip_file:
        for file_path in addon_dir.rglob("*"):
            if file_path.is_dir():
                continue
            arcname = str(Path(addon_id) / file_path.relative_to(addon_dir))
            zip_file.write(file_path, arcname)

    return zip_path


def clean_old_zips(addon_id: str, keep: Path) -> None:
    addon_zip_dir = ZIPS_DIR / addon_id
    if not addon_zip_dir.exists():
        return
    for file_path in addon_zip_dir.glob("*.zip"):
        if file_path != keep:
            file_path.unlink()


def generate_addons_xml(addon_xml_paths: list[Path]) -> str:
    xml_header = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    content = "<addons>\n"

    for addon_xml in addon_xml_paths:
        text = addon_xml.read_text(encoding="utf-8")
        text = re.sub(r"<\?xml.*?\?>", "", text, flags=re.DOTALL).strip()
        content += f"{text}\n"

    content += "</addons>\n"
    return xml_header + content


def write_md5(path: Path) -> None:
    md5_value = hashlib.md5(path.read_bytes()).hexdigest()  # nosec B324
    path.with_suffix(path.suffix + ".md5").write_text(md5_value, encoding="utf-8")


def main() -> None:
    args = parse_args()

    REPO_DIR.mkdir(parents=True, exist_ok=True)
    ZIPS_DIR.mkdir(parents=True, exist_ok=True)

    addon_xml_files: list[Path] = []

    for addon_name in args.addons:
        addon_dir = ROOT / addon_name
        addon_xml = addon_dir / "addon.xml"
        if not addon_xml.exists():
            raise FileNotFoundError(f"Missing addon.xml: {addon_xml}")

        tree = read_xml(addon_xml)
        root = tree.getroot()
        addon_id = root.attrib["id"]
        current_version = root.attrib["version"]

        if addon_name in args.bump:
            root.attrib["version"] = bump_patch(current_version)

        if addon_id == "repository.gloriosotv":
            update_repository_urls(tree, args.repo_url)

        source = root.find("./extension[@point='xbmc.addon.metadata']/source")
        if source is not None and "CHANGE_ME" in (source.text or ""):
            source.text = args.repo_url.replace("raw.githubusercontent.com", "github.com").replace("/main", "")

        write_xml(addon_xml, tree)

        version = tree.getroot().attrib["version"]
        zip_path = zip_addon(addon_dir, addon_id, version)
        clean_old_zips(addon_id, keep=zip_path)
        addon_xml_files.append(addon_xml)

    addons_xml_path = REPO_DIR / "addons.xml"
    addons_xml_path.write_text(generate_addons_xml(addon_xml_files), encoding="utf-8")
    write_md5(addons_xml_path)


if __name__ == "__main__":
    main()