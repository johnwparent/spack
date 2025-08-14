# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
"""Manages the default values used for generating container recipes"""

import sys


class Meta(type):
    def __getattribute__(cls, attr):
        os = "win" if sys.platform == "win32" else "nix"
        return object.__getattribute__(cls, os + attr)

class ImageDefaults(metaclass=Meta):
    """Stores information about default image attributes
    for each supported image platform"""

    # image registry keys
    winOs = "windows:2022"
    nixOs = "ubuntu:22.04"

    # image projection defaults
    winPaths = {
        "environment": "C:\\s\\env",
        "store": "C:\\s\\store",
        "view_parent": "C:\\v2",
        "view": "C:\\v2\\v",
        "former_view": "C:\\v"
    }
    nixPaths = {
        "environment": "/opt/spack-environment",
        "store": "/opt/software",
        "view_parent": "/opt/views",
        "view": "/opt/views/view",
        "former_view": "/opt/view"  # /opt/view -> /opt/views/view for backward compatibility
    }

    # Dockerfile multiline separators
    winMultiLineSep = "`"
    nixMultiLineSep = "\\"

    # Dockerfile template defaults
    winDockerTemplate = "container/Dockerfile.win"
    nixDockerTemplate = "container/Dockerfile.nix"


    def __init__(self, os):
        self._os = "win" if "windows" in os else "nix"

    def __getattr__(self, name: str):
        try:
            return self.__getattribute__(self._os + name)
        except AttributeError as e:
            raise AttributeError(f"ImageDefaults has no attribute {name}") from e