import jsonschema
from cpspy.schema import cps_package_schema

def validate(cps_json):
    """ Validate CPS Files """
    try:
        jsonschema.validate(instance=cps_json, schema=cps_package_schema)
        return True
    except jsonschema.ValidationError as e:
        print(f"Invalid Json Schema: {str(e)}")
        return False
    
