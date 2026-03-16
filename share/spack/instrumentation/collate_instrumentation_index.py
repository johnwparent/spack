# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
import argparse
import json
import sys

from pathlib import Path


def main(args):
    index_file = Path(args.index)
    destination = Path(args.destination)

    if not index_file.exists():
        raise RuntimeError(f"{index_file} is not available. Did you enable instrumentation?")

    with index_file.open() as f:
        data = json.load(f)
        data_dir = data.get("dataDir", None)
        trace = data.get("trace", None)
    if not (data_dir and trace):
        raise RuntimeError(f"Ill formed instrumentation index: {index_file}")
    data_dir = Path(data_dir)
    instrumentation_trace = data_dir / trace
    full_out = destination / "instrumentation" / index_file.stem
    full_out.mkdir(parents=True)
    for snippet in data["snippets"]:
        (data_dir / snippet).rename(full_out / snippet)

    instrumentation_trace.rename(full_out / instrumentation_trace.name)
    index_file.rename(full_out / index_file.name)


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument(
        "destination",
        action="store",
        help="Location to which instrumentation data will be collated"
    )
    args.add_argument(
        "index",
        action="store",
        help="Location of instrumentation index file"
    )
    collation_args = args.parse_args(sys.argv[1:])
    main(collation_args)
