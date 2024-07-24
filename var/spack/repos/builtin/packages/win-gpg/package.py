# Copyright 2013-2024 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
import re
import shutil

from spack.package import *


class WinGpg(Package):
    """GnuPG is a complete and free implementation of the OpenPGP
    standard as defined by RFC4880 (also known as PGP).

    This utility was cross compiled for x86_64 Windows
    systems via the Mingw-w64 cross compiler and a custom Spack repository
    """


    homepage = "https://gnupg.org/"
    url = "https://spack.github.io/windows-bootstrap-resources/resources/gpg/2.4.5/ggp4win_2.4.5.tar.gz"


    executables = ["^gpg$"]


    version("2.4.5", sha256="249ab87bd06abea3140054089bad44d9a5d1531413590576da609142db2673ec")

    provides("gpg")

    @classmethod
    def determine_version(cls, exe):
        output = Executable(exe)("--version", output=str, error=str)
        match = re.search(r"gpg (\S+)", output)
        return match.group(1) if match else None


    def install(self, spec, prefix):
        shutil.move(self.stage.source_path, prefix)