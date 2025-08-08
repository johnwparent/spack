# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
"""Manages the default values used for generating container recipes"""

import sys

from typing import Any

class Meta(type):
    def __getattribute__(cls, attr):
        os = "windows" if sys.platform == "win32" else "nix"
        return object.__getattribute__(cls, attr)[os]

class ImageDefaults(metaclass=Meta):
    OS = {
            "windows": "windows:2022",
            "nix": "ubuntu:22.04"
        }


class DefaultPaths:
    nix_paths = {
        "environment": "/opt/spack-environment",
        "store": "/opt/software",
        "view_parent": "/opt/views",
        "view": "/opt/views/view",
        "former_view": "/opt/view"  # /opt/view -> /opt/views/view for backward compatibility
    }
    # Windows has very terse path limitations, use shortest
    # possible prefixes wherever possible
    win_paths = {
        "environment": "C:\\s\\env",
        "store": "C:\\s\\software",
        "view_parent": "C:\\v2",
        "view": "C:\\v2\\v",
        "former_view": "C:\\v"
    }

    def __init__(self, os):
        self._os = os

    def __getattribute__(self, name: str) -> Any:
        if "windows" in self._os:
            return DefaultPaths.win_paths[name]
        else:
            return DefaultPaths.nix_paths[name]
