from typing import Any, Dict
from . import component, platform, requirement

from .common import list_of_string, json_string, str_to_lang_lst

properties: Dict[str, Any] = {
    "package" : {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "compat-version" : json_string,
                "components" : component.str_to_component,
                "configuration" : json_string,
                "configurations" : list_of_string,
                "cps-path" : json_string,
                "cps-version" : json_string,
                "default-components" : list_of_string,
                "name" : json_string,
                "platform" : platform.platform,
                "requires" : requirement.str_to_prop,
                "version" : json_string,
                "version-schema" : json_string,
            }
        }
    }
}


schema = {
     "type": "object",
    "additionalProperties": False,
    "properties": properties,
}

