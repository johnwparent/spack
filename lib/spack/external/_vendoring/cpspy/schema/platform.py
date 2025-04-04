from typing import Any, Dict

from .common import json_string

platform: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "c-runtime-vendor" : json_string,
        "c-runtime-version" : json_string,
        "clr-vendor" : json_string,
        "clr-version": json_string,
        "cpp-runtime-vendor" : json_string,
        "cpp-runtime-version" : json_string,
        "isa" : json_string,
        "jvm-vendor" : json_string,
        "jvm-version" : json_string,
        "kernel" : json_string,
        "kernel-version" : json_string
    }
}
