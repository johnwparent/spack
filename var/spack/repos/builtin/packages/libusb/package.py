# Copyright 2013-2024 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)


import glob
import os
import re
from spack.package import *


class Libusb(AutotoolsPackage, MSBuildPackage):
    """Library for USB device access."""

    homepage = "https://libusb.info/"
    url = "https://github.com/libusb/libusb/releases/download/v1.0.22/libusb-1.0.22.tar.bz2"
    git = "https://github.com/libusb/libusb"

    license("LGPL-2.1-or-later")

    version("master", branch="master")
    version("1.0.22", sha256="75aeb9d59a4fdb800d329a545c2e6799f732362193b465ea198f2aa275518157")
    version("1.0.21", sha256="7dce9cce9a81194b7065ee912bcd55eeffebab694ea403ffb91b67db66b1824b")
    version("1.0.20", sha256="cb057190ba0a961768224e4dc6883104c6f945b2bf2ef90d7da39e7c1834f7ff")

    variant("shared", default=True, description="Build shared libusb")

    depends_on("autoconf", type="build", when="@master build_system=autotools")
    depends_on("automake", type="build", when="@master build_system=autotools")
    depends_on("libtool", type="build", when="@master build_system=autotools")

    build_system("autotools", conditional("msbuild", when="platform=windows"))

    @when("@master build_system=autotools")
    def patch(self):
        mkdir("m4")


class AutotoolsBuilder(spack.build_systems.autotools.AutotoolsBuilder):
    def configure_args(self):
        args = []
        args.append("--disable-dependency-tracking")
        # no libudev/systemd package currently in spack
        args.append("--disable-udev")
        return args


class MSBuildBuilder(spack.build_systems.msbuild.MSBuildBuilder):
    @property
    def build_directory(self):
        return self.pkg.stage.source_path + "\\msvc"

    def is_64bit(self):
        return "64" in str(self.pkg.spec.target.family)

    def msbuild_args(self):
        compiler_sln = []
        with working_dir(self.build_directory):
            for obj in os.scandir():
                if obj.is_file() and re.match("libusb_[0-9]{4}.sln", obj.name):
                    compiler_sln.append(re.search("[0-9]{4}", obj.name).group(0))
        newest_supported_compiler = max(compiler_sln)
        return [f"libusb_{newest_supported_compiler}.sln"]

    def install(self, pkg, spec, prefix):
        plat = "x64" if self.is_64bit() else "x86"
        with working_dir(self.pkg.stage.source_path):
            libs = glob.glob(f"{self.pkg.stage.source_path}//{plat}/**/lib/*.lib")
            bin = glob.glob(f"{self.pkg.stage.source_path}//{plat}/**/dll/*.dll")
            imp_lib = glob.glob(f"{self.pkg.stage.source_path}//{plat}/**/dll/*.lib")
            headers = glob.glob(os.path.join(self.pkg.stage.source_path, "libusb", "*.h"))
            if "+shared" in spec:
                for lib in libs:
                    install(lib, prefix.lib)
            else:
                for binary in bin:
                    install(binary, prefix.bin)
                for lib in imp_lib:
                    install(lib, prefix.lib)
            for header in headers:
                install(header, prefix.include)
