# Copyright 2013-2024 Lawrence Livermore National Security, LLC and other
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
#     spack install libffi-meson
#
# You can edit this file again by typing:
#
#     spack edit libffi-meson
#
# See the Spack documentation for more information on packaging.
# ----------------------------------------------------------------------------

from spack.package import *


class LibffiMeson(MesonPackage):
    """The libffi library provides a portable, high level programming
    interface to various calling conventions. This allows a programmer
    to call any function specified by a call interface description at
    run time.

    This package is libffi ported to have a meson build system"""

    homepage = "https://sourceware.org/libffi/"
    url = "https://gitlab.freedesktop.org/gstreamer/meson-ports/libffi"
    git = "https://gitlab.freedesktop.org/gstreamer/meson-ports/libffi.git"

    license("MIT")

    version("meson", branch="meson")


    provides("ffi")


