from typing import Any, Dict

from .common import list_of_string, compile_features, compile_flags, includes, definitions

configuration: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
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
    }
}


str_to_conf: Dict[str, Any] = {
    "type" : "object",
    "additionalProperties" : False,
    "pattern_properties" : {
        "^.+$" : configuration
    }
}