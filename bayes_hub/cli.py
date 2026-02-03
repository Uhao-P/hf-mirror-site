#!/usr/bin/env python3
import os
import sys

if "HF_ENDPOINT" not in os.environ:
    os.environ["HF_ENDPOINT"] = "http://localhost:8080"

import huggingface_hub
from huggingface_hub import constants
constants.ENDPOINT = os.environ["HF_ENDPOINT"]

from huggingface_hub.commands.huggingface_cli import main as hf_main


def main():
    args = sys.argv.copy()

    if len(args) >= 2 and args[1] == "download":
        has_local_dir = any(arg.startswith("--local-dir") for arg in args if not arg.startswith("--local-dir-use-symlinks"))
        has_symlink_opt = any(arg.startswith("--local-dir-use-symlinks") for arg in args)

        if has_local_dir and not has_symlink_opt:
            args.append("--local-dir-use-symlinks=False")

    args[0] = "bayes-hub-cli"
    sys.argv = args
    return hf_main()


if __name__ == "__main__":
    sys.exit(main())
