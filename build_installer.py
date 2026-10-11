"""使用现有便携版 EXE 构建 NSIS 安装包；不修改已发布程序。

python build_installer.py --makensis <NSIS目录>/Bin/makensis.exe
NSIS 使用官方 ZIP 解压即可；不要求机器级安装。
"""
import argparse
import shutil
import subprocess
from pathlib import Path

from game import __version__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--makensis", default=shutil.which("makensis"))
    args = parser.parse_args()
    if not args.makensis:
        parser.error("未找到 makensis；请传入官方 NSIS ZIP 中编译器的路径")
    root = Path(__file__).resolve().parent
    for name in ("卡卡颂.exe", "使用说明.txt", "版本说明.txt"):
        if not (root / "release" / name).is_file():
            parser.error(f"缺少 release/{name}；请先生成便携版")
    subprocess.run([str(Path(args.makensis).resolve()), "/INPUTCHARSET", "UTF8", "/V2", f"/DVERSION={__version__}",
                    str(root / "installer.nsi")], cwd=root, check=True)


if __name__ == "__main__":
    main()
