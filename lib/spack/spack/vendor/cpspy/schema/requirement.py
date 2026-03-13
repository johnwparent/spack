from typing import Any, Dict

from .common import list_of_string, json_string

properties: Dict[str, Any] = {
    "type" : "object",
    "additionalProperties" : False,
    "properties" : {
        "components" : list_of_string,
        "hints" : list_of_string,
        "version" : json_string,
    }
}


str_to_prop: Dict[str, Any] = {
    "type" : "object",
    "additionalProperties" : False,
    "pattern_properties" : {
        "^.+$" : properties
    }
}