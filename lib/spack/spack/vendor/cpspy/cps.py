
import collections.abc
import copy

from typing import (
    Dict
)


"""Class representation of a CPS configuration"""

class ParserMeta(type):
    _dispatch = {}

    def __init__(cls, name, bases, attr_dict):
        for attr, parser in ParserMeta._dispatch.items():
            setattr(cls, f"{attr}_parser", parser)
        setattr(cls, "_default_parser", lambda x: x)
        ParserMeta._dispatch = {}
        super(ParserMeta, cls).__init__(name, bases, attr_dict)

    def parse(component):
        def wrapper(fun):
            ParserMeta._dispatch[component] = fun
            return fun
        return wrapper


class ParserMixin:
    @classmethod
    def from_dict(cls, cmp_dict: dict):
        kwargs = {}
        for attr in cmp_dict:
            kwargs[attr] = getattr(cls, f"{attr}_parser", cls._default_parser)(cmp_dict[attr])
        return cls(**kwargs)

    def validate(self):
        for var in self._required_attributes:
            if not getattr(self, var, None):
                raise CPSError(f"Required attribute {var} of {type(self)} not specified. Generated CPS file would be malformed")

    def to_dict(self) -> Dict:
        primitives = (bool, str, int, float, type(None))
        def _serialize_sequence(sequence):
            ret_seq = []
            for entry in sequence:
                if type(entry) in primitives:
                    ret_seq.append(entry)
                else:
                    ret_seq.append(entry.to_dict())
            return ret_seq

        def parse_dict(attr_dict):
            package_dict = dict()
            for attr in attr_dict.keys():
                if not isinstance(self, Package) and attr == "name":
                    continue
                val = attr_dict[attr]
                if val:
                    ret_val = copy.deepcopy(val)
                    if getattr(val, "to_dict", None):
                        ret_val = val.to_dict()
                    elif isinstance(val, Dict):
                        ret_val = parse_dict(val)
                    elif isinstance(val, collections.abc.Sequence) and not isinstance(val, str):
                        ret_val = _serialize_sequence(val)
                    real_attr = attr.lstrip("_")
                    package_dict[real_attr] = ret_val
            return package_dict
        package_dict = parse_dict(self.__dict__)
        return package_dict


parser = ParserMeta.parse


class Package(ParserMixin, metaclass=ParserMeta):
    """CPS Package object

    The Package is the root of the CPS Specification
    denoting the package the file is describing
    """
    def __init__(
            self,
            *,
            name=None,
            platform=None,
            prefix=None,
            version=None,
            version_scheme=None,
            compat_version=None,
            components=None,
            configuration=None,
            configurations=None,
            cps_path=None,
            cps_version=None,
            description=None,
            default_components=None,
            display_name=None,
            default_license=None,
            license=None,
            meta_comment=None,
            meta_schema=None,
            website=None,
            requires=None
        ):
        """"""
        self._name = name
        self._platform = platform
        self._prefix = prefix
        self._version = version
        self._version_scheme = version_scheme
        self._compat_version = compat_version
        self._components = components
        self._configuration = configuration
        self._configurations = configurations
        self._cps_path = cps_path
        self._cps_version = cps_version
        self._description = description
        self._default_components = default_components
        self._display_name = display_name
        self._default_license = default_license
        self._license = license
        self._meta_comment = meta_comment
        self._meta_schema = meta_schema
        self._website = website
        self._requires = requires
        super(Package, self).__init__()

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, val):
        self._name = val

    @property
    def platform(self):
        return self._platform

    @platform.setter
    def platform(self, val):
        self._platform = val

    @property
    def prefix(self):
        return self._prefix

    @prefix.setter
    def prefix(self, val):
        self._prefix = val

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, val):
        self._version = val

    @property
    def version_scheme(self):
        return self._version_scheme

    @version_scheme.setter
    def version_scheme(self, val):
        self._version_scheme = val

    @property
    def compat_version(self):
        return self._compat_version

    @compat_version.setter
    def compat_version(self, val):
        self._compat_version = val

    @property
    def components(self):
        return self._components

    @components.setter
    def components(self, val):
        self._components = val

    @property
    def configuration(self):
        return self._configuration

    @configuration.setter
    def configuration(self, val):
        self._configuration = val

    @property
    def configurations(self):
        return self._configurations

    @configurations.setter
    def configurations(self, val):
        self._configurations = val

    @property
    def cps_path(self):
        return self._cps_path

    @cps_path.setter
    def cps_path(self, val):
        self._cps_path = val

    @property
    def cps_version(self):
        return self._cps_version

    @cps_version.setter
    def cps_version(self, val):
        self._cps_version = val

    @property
    def default_components(self):
        return self._default_components

    @default_components.setter
    def default_components(self, val):
        self._default_components = val

    @property
    def requires(self):
        return self._requires

    @requires.setter
    def requires(self, val):
        self._requires = val

    @property
    def description(self):
        return self._description

    @description.setter
    def description(self, val):
        self._description = val

    @staticmethod
    @parser("components")
    def _parse_components(cmps):
        components = {}
        for x in cmps:
            components[x] = Component.from_dict(cmps[x])
        return components

    @staticmethod
    @parser("requires")
    def _parse_requirements(reqs):
        requirements = {}
        for x in reqs:
            requirements[x] = Requirement.from_dict(reqs[x])
        return requirements

    @staticmethod
    @parser("platform")
    def _parser_platform(platform):
        return Platform(**platform)

    def add_requirement(self, *requirements):
        if not self._requires:
            self._requires = {}
        for requirement in requirements:
            self._requires[requirement.name] = requirement

    def add_component(self, *components):
        if not self._components:
            self._components = {}
        for component in components:
            self._components[component.name] = component

    def add_configuration(self, *configurations):
        if not self._configurations:
            self._configurations = []
        self._configurations.extend(configurations)

    def add_default_components(self, *components):
        if not self._default_components:
            self._default_components = []
        self._default_components.extend(components)


class Platform(ParserMixin, metaclass=ParserMeta):
    """CPS Platform object"""
    def __init__(
            self,
            *,
            c_runtime_vendor=None,
            c_runtime_version=None,
            cpp_runtime_version=None,
            cpp_runtime_vendor=None,
            clr_vendor=None,
            clr_version=None,
            isa=None,
            kernel=None,
            kernel_version=None,
            jvm_vendor=None,
            jvm_version=None,
        ):
        """"""
        self._c_runtime_vendor = c_runtime_vendor
        self._c_runtime_version = c_runtime_version
        self._cpp_runtime_version = cpp_runtime_version
        self._cpp_runtime_vendor = cpp_runtime_vendor
        self._clr_vendor = clr_vendor
        self._clr_version = clr_version
        self._isa = isa
        self._kernel = kernel
        self._kernel_version = kernel_version
        self._jvm_vendor = jvm_vendor
        self._jvm_version = jvm_version

    @property
    def c_runtime_vendor(self):
        return self._c_runtime_vendor

    @c_runtime_vendor.setter
    def c_runtime_vendor(self, val):
        self._c_runtime_vendor = val

    @property
    def c_runtime_version(self):
        return self._c_runtime_version

    @c_runtime_version.setter
    def c_runtime_version(self, val):
        self._c_runtime_version = val

    @property
    def cpp_runtime_version(self):
        return self._cpp_runtime_version

    @cpp_runtime_version.setter
    def cpp_runtime_version(self, val):
        self._cpp_runtime_version = val

    @property
    def cpp_runtime_vendor(self):
        return self._cpp_runtime_vendor

    @cpp_runtime_vendor.setter
    def cpp_runtime_vendor(self, val):
        self._cpp_runtime_vendor = val

    @property
    def clr_vendor(self):
        return self._clr_vendor

    @clr_vendor.setter
    def clr_vendor(self, val):
        self._clr_vendor = val

    @property
    def clr_version(self):
        return self._clr_version

    @clr_version.setter
    def clr_version(self, val):
        self._clr_version = val

    @property
    def isa(self):
        return self._isa

    @isa.setter
    def isa(self, val):
        self._isa = val

    @property
    def jvm_vendor(self):
        return self._jvm_vendor

    @jvm_vendor.setter
    def jvm_vendor(self, val):
        self._jvm_vendor = val

    @property
    def jvm_version(self):
        return self._jvm_version

    @jvm_version.setter
    def jvm_version(self, val):
        self._jvm_version = val

    @property
    def kernel(self):
        return self._kernel

    @kernel.setter
    def kernel(self, val):
        self._kernel = val

    @property
    def kernel_version(self):
        return self._kernel_version

    @kernel_version.setter
    def kernel_version(self, val):
        self._kernel_version = val


class Requirement(ParserMixin, metaclass=ParserMeta):
    """CPS Requirement object"""
    def __init__(self, *, name=None, components=None, hints=None, requires=None, version=None):
        """"""
        self._name = name
        self._components = components
        self._hints = hints
        self._requires = requires
        self._version = version

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, val):
        self._name = val

    @property
    def components(self):
        return self._components

    @components.setter
    def components(self, val):
        self._components = val

    @property
    def hints(self):
        return self._hints

    @hints.setter
    def hints(self, val):
        self._hints = val

    @property
    def requires(self):
        return self._requires

    @requires.setter
    def requires(self, val):
        self._requires = val

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, val):
        self._version = val

    def add_component(self, *components):
        if not self._components:
            self._components = []
        self._components.extend(components)


class Component(ParserMixin, metaclass=ParserMeta):
    """CPS Component object"""
    def __init__(self, *,
                 name=None,
                 type=None,
                 configurations=None,
                 compile_features=None,
                 compile_flags=None,
                 definitions=None,
                 includes=None,
                 link_features=None,
                 link_flags=None,
                 link_libraries=None,
                 link_languages=None,
                 link_location=None,
                 link_requires=None,
                 location=None,
                 requires=None,
                 description=None,
                 license=None
                 ):
        """"""
        self._name = name
        self._configurations = configurations
        self._type = type
        self._compile_features = compile_features
        self._compile_flags = compile_flags
        self._definitions = definitions
        self._includes = includes
        self._link_features = link_features
        self._link_flags = link_flags
        self._link_languages = link_languages
        self._link_libraries = link_libraries
        self._link_location = link_location
        self._link_requires = link_requires
        self._location = location
        self._requires = requires
        self._license = license
        self._description = description

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, val):
        self._name = val

    @property
    def type(self):
        return self._type

    @type.setter
    def type(self, val):
        self._type = val

    @property
    def compile_features(self):
        return self._compile_features

    @compile_features.setter
    def compile_features(self, val):
        self._compile_features = val

    @property
    def compile_flags(self):
        return self._compile_flags

    @compile_flags.setter
    def compile_flags(self, val):
        self._compile_flags = val

    @property
    def definitions(self):
        return self._definitions

    @definitions.setter
    def definitions(self, val):
        self._definitions = val

    @property
    def includes(self):
        return self._includes

    @includes.setter
    def includes(self, val):
        self._includes = val

    @property
    def link_features(self):
        return self._link_features

    @link_features.setter
    def link_features(self, val):
        self._link_features = val

    @property
    def link_flags(self):
        return self._link_flags

    @link_flags.setter
    def link_flags(self, val):
        self._link_flags = val

    @property
    def link_languages(self):
        return self._link_languages

    @link_languages.setter
    def link_languages(self, val):
        self._link_languages = val

    @property
    def link_libraries(self):
        return self._link_libraries

    @link_libraries.setter
    def link_libraries(self, val):
        self._link_libraries = val

    @property
    def link_location(self):
        return self._link_location

    @link_location.setter
    def link_location(self, val):
        self._link_location = val

    @property
    def link_requires(self):
        return self._link_requires

    @link_requires.setter
    def link_requires(self, val):
        self._link_requires = val

    @property
    def location(self):
        return self._location

    @location.setter
    def location(self, val):
        self._location = val

    @property
    def requires(self):
        return self._requires

    @requires.setter
    def requires(self, val):
        self._requires = val

    @property
    def description(self):
        return self._description

    @description.setter
    def description(self, val):
        self._description = val

    @property
    def configurations(self):
        return self._configurations

    @configurations.setter
    def configurations(self, val):
        self._configurations = val

    @staticmethod
    @parser("configurations")
    def _parse_configurations(configs):
        component_configs = {}
        for x in configs:
            component_configs[x] = Configuration.from_dict(configs[x])
        return component_configs

    def add_config(self, *configs):
        if not self._configurations:
            self._configurations = {}
        for config in configs:
            self._configurations[config.name] = config

    def add_requires(self, *requires):
        if not self._requires:
            self._requires = []
        self._requires.extend(requires)


class Configuration(ParserMixin, metaclass=ParserMeta):
    """CPS Configuration object"""
    def __init__(self, *,
                name=None,
                compile_features=None,
                compile_flags=None,
                definitions=None,
                includes=None,
                link_features=None,
                link_flags=None,
                link_languages=None,
                link_libraries=None,
                link_location=None,
                link_requires=None,
                location=None,
                requires=None,
        ):
        """"""
        self._name = name
        self._compile_features = compile_features
        self._compile_flags = compile_flags
        self._definitions = definitions
        self._includes = includes
        self._link_features = link_features
        self._link_flags = link_flags
        self._link_languages = link_languages
        self._link_libraries = link_libraries
        self._link_location = link_location
        self._link_requires = link_requires
        self._location = location
        self._requires = requires

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, val):
        self._name = val

    @property
    def compile_features(self):
        return self._compile_features

    @compile_features.setter
    def compile_features(self, val):
        self._compile_features = val

    @property
    def compile_flags(self):
        return self._compile_flags

    @compile_flags.setter
    def compile_flags(self, val):
        self._compile_flags = val

    @property
    def definitions(self):
        return self._definitions

    @definitions.setter
    def definitions(self, val):
        self._definitions = val

    @property
    def includes(self):
        return self._includes

    @includes.setter
    def includes(self, val):
        self._includes = val

    @property
    def link_features(self):
        return self._link_features

    @link_features.setter
    def link_features(self, val):
        self._link_features = val

    @property
    def link_flags(self):
        return self._link_flags

    @link_flags.setter
    def link_flags(self, val):
        self._link_flags = val

    @property
    def link_languages(self):
        return self._link_languages

    @link_languages.setter
    def link_languages(self, val):
        self._link_languages = val

    @property
    def link_libraries(self):
        return self._link_libraries

    @link_libraries.setter
    def link_libraries(self, val):
        self._link_libraries = val

    @property
    def link_location(self):
        return self._link_location

    @link_location.setter
    def link_location(self, val):
        self._link_location = val

    @property
    def link_requires(self):
        return self._link_requires

    @link_requires.setter
    def link_requires(self, val):
        self._link_requires = val

    @property
    def location(self):
        return self._location

    @location.setter
    def location(self, val):
        self._location = val

    @property
    def requires(self):
        return self._requires

    @requires.setter
    def requires(self, val):
        self._requires = val

    def add_requires(self, *requires):
        if not self._requires:
            self._requires = []
        self._requires.extend(requires)


class CPSError(RuntimeError):
    """Base class defining CPS derived runtime errors"""
