# Copyright 2013-2024 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack.package import *


class Portaudio(CMakePackage):
    """PortAudio is a cross-platform, open-source C language library for real-time audio input and output."""
    homepage = "https://www.portaudio.com/"
    url = "https://github.com/PortAudio/portaudio/archive/refs/tags/v19.7.0.tar.gz"
    git = "https://github.com/PortAudio/portaudio.git"


    version("19.7.0", sha256="5af29ba58bbdbb7bbcefaaecc77ec8fc413f0db6f4c4e286c40c3e1b83174fa0")
