#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
manifest.py —— 扫描 info/heros/ 下各奥特曼文件夹，将「图片与音频的存在情况」
补充进同级的 info/metainfo.json。

设计原则（对应需求三条）：
  1) 只读 metainfo.json，绝不修改用户手动维护的「静态信息」：
     cn / en / jp / year / works / skill / image / rarity /
     *_local / github_matched …… 以及顶层 count / justfor 等一律原样保留。
  2) 仅在每个英雄条目上「新增 / 整体刷新」脚本拥有的字段 media：
       - media.scanned_at : 本次扫描时间（ISO8601, UTC）
       - media.images     : 各图片是否存在 {fullbody, babytype, logo, thumbnail}
       - media.audio      : 扫描到的音频相对路径列表（heros/<folder>/audio*.mp3）
     media 之外的字段一律不动；media 每次运行整体重建（属于脚本产物）。
  3) 匹配方式：扫描 info/heros/ 下的真实子文件夹，按「文件夹名」与 metainfo 中英雄对应
     （文件夹名取自各英雄 *_local 路径里的 heros/<folder>/…）。
       - 已匹配英雄：写入其 media。
       - 磁盘有、但 metainfo 无对应条目的文件夹：追加最小 stub（仅 folder + media），
         方便后续手动补全静态信息，并打印提示。
       - metainfo 有、但磁盘无该文件夹的英雄：media 置空并提示。

用法：
    python manifest.py                # 默认：脚本所在目录即 info/，扫描 info/heros/
    python manifest.py /path/to/info  # 指定 info 根目录
"""
import json
import os
import sys
import glob
from datetime import datetime, timezone

# metainfo 中的手动字段  ->  media.images 中的键
IMAGE_KEYS = {
    "fullbody_local": "fullbody",
    "babytype_local": "babytype",
    "logo_local": "logo",
    "thumbnail_local": "thumbnail",
}
# 当 *_local 缺失时，回退探测的文件名
FALLBACK_IMG = {
    "fullbody": "fullbody.png",
    "babytype": "babytype.png",
    "logo": "logo.png",
    "thumbnail": "thumbnail.png",
}


def folder_of(hero):
    """从 hero 的 *_local 路径里提取 heros/ 下的文件夹名，如 01_初代奥特曼。"""
    for k in IMAGE_KEYS:
        v = hero.get(k)
        if not v:
            continue
        parts = v.replace("\\", "/").split("/")
        if "heros" in parts:
            i = parts.index("heros")
            if i + 1 < len(parts):
                return parts[i + 1]
    return None


def scan_folder(heros_root, folder, hero=None):
    d = os.path.join(heros_root, folder)
    images = {}
    for local_key, media_key in IMAGE_KEYS.items():
        fname = None
        if hero:
            v = hero.get(local_key)          # 例如 heros/01_初代奥特曼/thumbnail.jpg
            if v:
                fname = os.path.basename(v.replace("\\", "/"))
        if not fname:
            fname = FALLBACK_IMG[media_key]
        images[media_key] = os.path.isfile(os.path.join(d, fname))
    audio = sorted(
        os.path.basename(p)
        for p in glob.glob(os.path.join(d, "audio*"))
        if os.path.isfile(p)
    )
    audio_paths = ["heros/%s/%s" % (folder, a) for a in audio]
    return images, audio_paths


def main():
    info_root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    info_root = os.path.abspath(info_root)
    metainfo_path = os.path.join(info_root, "metainfo.json")
    heros_root = os.path.join(info_root, "heros")

    if not os.path.isfile(metainfo_path):
        print("错误：未找到 %s，请先放置手动维护的 metainfo.json。" % metainfo_path)
        sys.exit(1)

    with open(metainfo_path, encoding="utf-8") as f:
        data = json.load(f)
    heroes = data.get("heroes", [])
    n0 = len(heroes)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    matched_folders = set()
    appended = 0

    # 1) 遍历已有英雄，刷新 media（不会改动任何静态字段）
    for hero in heroes:
        folder = folder_of(hero)
        cn = hero.get("cn") or hero.get("en") or "?"
        if not folder:
            print("  [跳过] 英雄 %s：无法从 *_local 推断文件夹，未扫描。" % cn)
            continue
        d = os.path.join(heros_root, folder)
        if not os.path.isdir(d):
            print("  [缺文件夹] %s：metainfo 有记录但磁盘无此文件夹，media 置空。" % folder)
            hero["media"] = {
                "scanned_at": now,
                "images": {k: False for k in IMAGE_KEYS.values()},
                "audio": [],
            }
            continue
        images, audio_paths = scan_folder(heros_root, folder, hero)
        hero["media"] = {"scanned_at": now, "images": images, "audio": audio_paths}
        matched_folders.add(folder)
        print("  [OK] %s: images=%s, audio=%s" % (folder, images, audio_paths))

    # 2) 磁盘上多出来的文件夹 -> 追加最小 stub（静态信息留待手动补全）
    if os.path.isdir(heros_root):
        for name in sorted(os.listdir(heros_root)):
            d = os.path.join(heros_root, name)
            if not os.path.isdir(d) or name in matched_folders:
                continue
            print("  [新增] 发现未登记文件夹 %s，追加最小 stub（请手动补全静态信息）。" % name)
            images, audio_paths = scan_folder(heros_root, name)
            stub = {
                "index": len(heroes) + 1,
                "cn": name,
                "en": name,
                "folder_hint": name,
                "media": {"scanned_at": now, "images": images, "audio": audio_paths},
            }
            heroes.append(stub)
            matched_folders.add(name)
            appended += 1

    data["heroes"] = heroes
    # 注意：不改动 count / justfor 等顶层静态字段，原样保留。

    with open(metainfo_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("已更新 %s：原有英雄 %d 个全部刷新，新增 stub %d 个，共 %d 条记录。"
          % (metainfo_path, n0, appended, len(heroes)))


if __name__ == "__main__":
    main()
