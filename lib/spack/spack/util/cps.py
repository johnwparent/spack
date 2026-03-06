# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
import json
import os
import pathlib
import platform
import re
import sys

from cpspy import cps

from typing import (
    Optional
)

from llnl.util.filesystem import find_all_static_libraries, find_all_shared_libraries

import spack.spec
import spack.deptypes as dt
import spack.compilers.libraries

from spack.version import StandardVersion

SPACK_CPS_VERSION = StandardVersion.from_string("0.13.0")


class SpackCps:

    def __init__(self, pkg_spec: spack.spec.Spec, package: Optional[cps.Package]=None):
        self._spec = pkg_spec
        self._package = package or self.from_spec(self._spec)
        self._confs = []
        self._components = []

    @property
    def component_qualifier(self):
        return self.cps_name+":"

    def populate_compile_context(self):
        pass

    @staticmethod
    def target_to_platform(spec):
        target = spec.target
        cps_platform = {}
        cps_platform["isa"] = target.family.name
        cps_platform["kernel"] = platform.uname().system
        if not sys.platform == "win32":
            try:
                libc = spack.compilers.libraries.CompilerPropertyDetector(spec.compiler.spec).default_libc()
            except:
                libc = None
            if libc:
                cps_platform["c_runtime_version"] = libc.version
                cps_platform["cpp_runtime_version"] = libc.version

                vendor_mappings =  {
                    "glibc" : "gnu"
                }

                if "glibc" in str(libc):
                    cps_platform["c_runtime_vendor"] = "gnu"
                    cps_platform["cpp_runtime_vendor"] = "gnu"
                elif "musl" in str(libc):
                    cps_platform["c_runtime_vendor"] = "musl"
                    cps_platform["cpp_runtime_vendor"] = "musl"
                elif "llvm" in str(libc):
                    cps_platform["c_runtime_vendor"] = "llvm"
                    cps_platform["cpp_runtime_vendor"] = "llvm"
                elif "libstdc" in str(libc) or "libstdc++" in str(libc):
                    cps_platform["c_runtime_vendor"] = "bsd"
                    cps_platform["cpp_runtime_vendor"] = "bsd"
            else:
                if "gcc" in spec:
                    cps_platform["c_runtime_vendor"] = "gnu"
                    cps_platform["cpp_runtime_vendor"] = "gnu"
                elif "clang" in spec:
                    cps_platform["c_runtime_vendor"] = "llvm"
                    cps_platform["cpp_runtime_vendor"] = "llvm"
        else:
            if "msvc" in spec:
                cps_platform["c_runtime_vendor"] = "microsoft"
                cps_platform["cpp_runtime_vendor"] = "microsoft"
                cps_platform["clr_vendor"] = "microsoft"
                cps_platform["c_runtime_version"] = spec["msvc"].package.msvc_version
                cps_platform["cpp_runtime_version"] = spec["msvc"].package.msvc_version
        return cps_platform

    def _process_runtime_vendor(self):


    def get_compiler_args(self):
        args = []
        if self._spec.compiler:
            compiler_pkg = self._spec.compiler.spec.package
            args.append(compiler_pkg.verbose_flags)
            if "openmp" in self._spec:
                args.append(compiler_pkg.openmp_flag)
            if self._spec.satisfies("+pic") or self._spec.satisfies("+shared"):
                args.append(compiler_pkg.pic_flag)
            for flag_name, value in self._spec.compiler_flags.items():
                if value:
                    args.extend(value)
            args.extend(
                self._spec.target.optimization_flags(
                    self._spec.compiler.name,
                    str(self._spec.compiler.version)
                )
            )
        return args

    def get_linker_args(self):
        args = []
        if self._spec.compiler:
            compiler_pkg = self._spec.compiler.spec.package
            args.append(compiler_pkg.linker_arg)
            args.append(compiler_pkg.rpath_arg)
            if getattr(self._spec.package, "libs", None):
                args.append(self._spec.package.libs.ld_flags)
        return args

    def setup_configurations(self):
        # setup build type config
        bt_conf = None
        if "debug" in self._spec.variants:
            if self._spec.satisfies("+debug"):
                bt_conf = cps.Configuration(name="debug")
            else:
                bt_conf = cps.Configuration(name="optimized")
        elif "build_type" in self._spec.variants:
            bt = self._spec.variants["build_type"].value
            conf = "debug" if "debug" in bt else "optmized"
            bt_conf = cps.Configuration(name=conf)
        if bt_conf:
            bt_conf.add_requires(self.component_qualifier+self.core_component_name)
            bt_component = cps.Component(name=self.cps_name+"-"+bt_conf.name)
            bt_component.add_config(bt_conf)
        # Setup shared vs static vs both
        # If "shared" is an option, we assume the project
        # only vendors shared as we cannot determine if it
        # also build static
        if "shared" in self._spec.variants:
            if self._spec.satisfies("+shared"):
                self._confs.append(cps.Configuration(name="shared"))
            else:
                self._confs.append(cps.Configuration(name="static"))
        elif "libs" in self._spec.variants:
            bt = self._spec.variants["libs"].value
            if isinstance(bt, tuple):
                cnfa, cnfb = bt[0], bt[1]
                self._confs.append(cps.Configuration(name=cnfa))
                self._confs.append(cps.Configuration(name=cnfb))
            else:
                self._confs.append(cps.Configuration(name=bt))
        for conf in self._confs:
            if bt_conf:
                req = bt_component.name
            else:
                req = self.core_component_name
            conf.add_requires(self.component_qualifier+req)

    def pkg_to_components(self):
        hsh_comp_list = []
        def add_dual_components(name, location, type=None, add_base_requirement=True):
            comp = cps.Component(name=name, location=str(location), type=type)
            comp_hash_name = f"{name}-{self._spec.dag_hash()[:6]}"
            comp_hash = cps.Component(
                name=comp_hash_name,
                requires=[self.component_qualifier+comp.name],
                type="interface"
            )
            self._package.add_component(comp, comp_hash)
            self._components.append((comp, comp_hash))
            if add_base_requirement:
                hsh_comp_list.append(self.component_qualifier+comp_hash_name)
        package = self._spec.package
        for artifact_dir in ["lib", "lib64"]:
            for lib in find_all_shared_libraries(getattr(package.prefix, artifact_dir)):
                add_dual_components(
                    os.path.basename(lib).split(".")[0],
                    lib,
                    type="dylib"
                )
            for lib in find_all_static_libraries(getattr(package.prefix, artifact_dir)):
                add_dual_components(
                    os.path.basename(lib).split(".")[0],
                    lib, type="archive"
                )
        bin_dir = pathlib.Path(getattr(package.prefix, "bin"))
        if bin_dir.exists():
            for pth in bin_dir.iterdir():
                if pth.exists() and os.access(pth, os.X_OK):
                    # disable requirement from root of package to executables because
                    # cmake cannot properly process them
                    add_dual_components(pth.stem, str(pth), type="executable", add_base_requirement=False)
        if sys.platform=="win32":
            # windows installs shared libraries in the BIN
            for lib in find_all_shared_libraries(getattr(package.prefix, "bin")):
                # Make dlls available for runtime loading, but don't require them
                add_dual_components(os.path.basename(lib), lib, type="dylib", add_base_requirement=False)
        if pathlib.Path(package.prefix.include).exists():
            add_dual_components("headers", package.prefix.include, type="interface")
        includes = []
        if os.path.exists(package.prefix.include):
            includes.append(str(package.prefix.include))
        try:
            linker_args = self.get_linker_args()
            compiler_args = self.get_compiler_args()
        except:
            linker_args = []
            compiler_args = []
        ch = cps.Component(name=self.core_component_name,
                           requires=hsh_comp_list,
                           type="interface",
                           includes=includes,
                           link_flags=linker_args,
                           compile_flags=compiler_args)
        c = cps.Component(name=self.cps_name,
                          type="interface"
                          )
        # c.add_config(*self._confs)
        c.add_requires(self.component_qualifier+self.core_component_name)
        self.add_component(c)
        self.add_component(ch)

    def add_component(self, component):
        self._package.add_component(component)

    def add_config(self, component, config):
        self._package.components[component.name].add_config(config)

    @property
    def cps_name(self):
        return self._spec.package.name

    @property
    def core_component_name(self):
        return f"{self.cps_name}-core"

    @property
    def hint(self):
        return self._spec.prefix

    @property
    def requirements(self):
        "interface requirement for usage constraints, headers, flags, etc"
        pass

    def to_dict(self):
        return self._package.to_dict()

    @classmethod
    def from_dict(cls, pkg_dict, spec):
        package = cps.Package.from_dict(pkg_dict)
        return SpackCps(spec, package=package)

    @classmethod
    def to_package(cls, pkg_spec: spack.spec.Spec) -> cps.Package:
        assert pkg_spec.concrete, "Cannot produce meaningful CPS with un concretized specs"
        name = pkg_spec.name
        description = pkg_spec.package.__doc__ + "\n" + pkg_spec.dag_hash()[:6]
        license = " AND ".join(pkg_spec.package.licenses.values())
        cps_package_version = str(pkg_spec.version)
        version_scheme = "custom"
        if re.match(r"[0-9]+([.][0-9]+)*([-+].*)?", cps_package_version):
            version_scheme = "simple"
        cps_plat = cps.Platform(**SpackCps.target_to_platform(pkg_spec))
        cps_pkg = cps.Package(name=name,
                              description=description,
                              license=license,
                              version=cps_package_version,
                              version_scheme=version_scheme,
                              platform=cps_plat,
                              cps_version=str(SPACK_CPS_VERSION),
                              cps_path=pkg_spec.package.get_cps_prefix()
                            )
        spack_cps = SpackCps(pkg_spec, cps_pkg)
        spack_cps.setup_configurations()
        spack_cps.pkg_to_components()
        for spec in pkg_spec.dependencies(deptype=dt.RUN | dt.LINK):
            requirement_version = spec.version
            hint = spec.prefix
            component = f"{spec.package.name}:{name}-{spec.dag_hash()[:6]}"
            req = cps.Requirement(
                name=spec.name,
                version=str(requirement_version),
                hints=[str(hint)]
            )
            req.add_component(component)
            cps_pkg.add_requirement(req)
        for variant in pkg_spec.variants:
            # special case cmake config analogs
            if pkg_spec.satisfies(variant) \
                and variant not in ("shared", "libs", "debug", "build_type"):
                sym_comp = cps.Component(
                    name=variant.name,
                    type="symbolic",
                    requires=[f"{spack_cps.component_qualifier+spack_cps.core_component_name}"]
                )
                spack_cps.add_component(sym_comp)
        return spack_cps

    @staticmethod
    def from_spec(pkg_spec: spack.spec.Spec):
        """Takes a concrete spec representing the installation of a package
        and produces a CPS file"""
        assert pkg_spec.concrete, "Cannot produce meaningful CPS with un concretized specs"
        cps_pkg = SpackCps.to_package(pkg_spec)
        return SpackCps(pkg_spec, package=cps_pkg)


def spec_to_cps_to_disc(pkg_spec: spack.spec.Spec):
    spack_cps = SpackCps.from_spec(pkg_spec)
    pathlib.Path(
        pkg_spec.package.cps_file_path
    ).parent.mkdir(parents=True, exist_ok=True)
    with open(pkg_spec.package.cps_file_path, "w") as f:
        f.write(json.dumps(spack_cps.to_dict(), indent=2))


def spec_to_cps(pkg_spec: spack.spec.Spec) -> SpackCps:
    return SpackCps.from_spec(pkg_spec)
