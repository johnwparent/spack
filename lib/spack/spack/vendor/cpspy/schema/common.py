
json_string = { "type" : "string" }
list_of_string = { "type" : "array", "items" : "string" }

str_to_lang_lst = { "type" : "object",
                   "additionalProperties" : False,
                   "properties" : {
                    "C" : list_of_string,
                    "C++" : list_of_string,
                    "Fortran" : list_of_string
                   } 
                }
compile_features = { "compile-features" : list_of_string }
compile_flags = { 
    "compile-flags" : {
        "oneOf" : [
            list_of_string,
            str_to_lang_lst
        ]
    }
}
definitions = { 
                "type" : {
                    "oneOf" : [
                        list_of_string,
                        str_to_lang_lst
                    ]
                }
            }
includes = { 
    "type" : {
        "oneOf" : {
            list_of_string,
            str_to_lang_lst
        }
    }
}

