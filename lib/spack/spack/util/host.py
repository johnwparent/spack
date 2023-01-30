# Copyright 2013-2023 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import platform

class WindowsDetection:
    def detect(self):
        return "cygwin" in self.plat or "win32" in self.plat or "windows" in self.plat


class Detection:
    def __init__(self, cls):
        self.plat = platform.system.lower()


def detect(cls):
    return Detection(cls).detect()
