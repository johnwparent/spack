# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
import os
import shutil
import sys

import spack.paths
import spack.store
import spack.tengine
import spack.llnl.util.filesystem as sfsys


def collation_location(spec):
    return os.path.join(spec.package.stage.path, "instrumentation", "data")


def pre_install(spec):
    if "cmake" in spec:
        env = spack.tengine.make_environment()
        template = env.get_template("instrumentation/query.json")
        context = {
            "collator_script" : os.path.join(spack.paths.share_path, "instrumentation", "collate_instrumentation_index.py"),
            "collation_location" : collation_location(spec),
            "spack_python" : sys.executable,
        }
        instrumentation_dir = os.path.join(spec.package.stage.path, "instrumentation-ec7aa2dc-b87f-45a3-8022-fe01c5f59984/v1/query")
        sfsys.mkdirp(instrumentation_dir)
        with open(os.path.join(instrumentation_dir, "query.json"), "w+", encoding="utf-8") as f:
            f.write(template.render(context))


def post_install(spec, explicit=None):
    """Run ctest to compose all collected
    instrumentation data into a single index
    and relocate in the install tree
    """
    if "cmake" in spec:
        metadata_location = os.path.join(
            spec.prefix,
            spack.store.STORE.layout.metadata_dir,
        )
        if os.path.exists(collation_location(spec)):
            sfsys.copy_tree(collation_location(spec), os.path.join(metadata_location, "instrumentation"))
