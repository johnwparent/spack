# Copyright 2013-2023 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

# ----------------------------------------------------------------------------
# If you submit this package back to Spack as a pull request,
# please first remove this boilerplate and all FIXME comments.
#
# This is a template package file for Spack.  We've put "FIXME"
# next to all the things you'll want to change. Once you've handled
# them, you can save this file and test your package like this:
#
#     spack install win-gpg
#
# You can edit this file again by typing:
#
#     spack edit win-gpg
#
# See the Spack documentation for more information on packaging.
# ----------------------------------------------------------------------------

from spack.package import *


class Gpg4win(Package):
    """Windows "port" of GPG by the Gnu32 project
    This is not a true port as building from source still
    requires autotools and a posix environment/non native Windows
    compilers. As a result, we are only able to use the distributed
    binaries for the time being."""

    homepage = "https://www.gpg4win.org"
    url = "https://files.gpg4win.org/gpg4win-4.2.0.exe"

    maintainers("johnwparent")

    version("4.2.0", sha256="829b5c8eb913fa383abdd4cf129a42e0f72d4e9924b2610134f593851f0ab119", expand=False)
    version("4.1.0", sha256="e0fddc840808eef9531f14a515f8b3b6c46511977f00569161129c1dee413b38", expand=False)
    version("4.0.4", sha256="a750608969a075f132da31f538231ac3a2d3538e3eec8e8603d1573284745d0e", expand=False)
    version("4.0.0", sha256="f83be101c5e9c23740d6fde55fd8fefebf4fafb7badcb3756d1f574b5ad37507", expand=False)
    version("3.1.16", sha256="c499213ff3e14e93c3b245546994cc0e654ec267b40a188788665ae8f4e9f5ad", expand=False)


    def url_for_version(self, version):
        return f"https://files.gpg4win.org/gpg4win-{str(version)}.exe"

    def install(self, spec, prefix):
        wingpg_installer = Executable(self.stage.archive_file)
        args = ["/S", f"/D={prefix}"]
        wingpg_installer(*args)
