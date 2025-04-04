from typing import Any, Dict

from .common import list_of_string, compile_features, compile_flags, definitions
from . import configuration

component: Dict[str, Any] = {
    "type": "object",
    "additionalProperties" : False,
    "properties": {
        "configurations" : configuration.str_to_conf,
        "compile-features" : compile_features,
        "compile-flags" : compile_flags,
        "definitions" : definitions,
        "includes" : includes,
        "link-features" : list_of_string,
        "link-flags" : list_of_string,
        "link-languages" : list_of_string,
        "link-libraries" : list_of_string,
        "link-location" : json_string,
        "link-requires" : list_of_string,
        "location" : json_string,
        "requires" : list_of_string,
        "type" : json_string,
    }
}


str_to_component = {
    "type" : "object",
    "additionalProperties" : False,
    "pattern_properties" : {
        "^.+$" : component
    }
}
