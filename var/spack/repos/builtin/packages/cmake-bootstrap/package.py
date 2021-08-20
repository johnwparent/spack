# Copyright 2013-2021 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import re

from llnl.util import filesystem as fs

from spack import *

class CmakeBootstrap(Package):
    """A cross-platform, open-source build system. CMake is a family of
    tools designed to build, test and package software.
    """
    homepage = 'https://www.cmake.org'
    url = 'https://github.com/Kitware/CMake/releases/download/v3.19.0/cmake-3.19.0.tar.gz'
    maintainers = ['chuckatkins']

    tags = ['build-tools']

    executables = ['^cmake$']

    version('3.21.1', sha256='9fba6df0b89be0dc0377f2e77ca272b3f8c38691fe237699de275ea0c2254242', url='https://github.com/Kitware/CMake/releases/download/v3.21.1/cmake-3.21.1-windows-x86_64.zip', expand=True)

    @classmethod
    def determine_version(cls, exe):
        output = Executable(exe)('--version', output=str, error=str)
        match = re.search(r'cmake.*version\s+(\S+)', output)
        return match.group(1) if match else None

    def install(self, spec, prefix):
        fs.copy_tree(self.stage.source_path, prefix)


