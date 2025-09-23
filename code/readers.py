import yaml

def readProfile(yaml_profile):
    with open(yaml_profile, 'r') as file:
        loaded_data = yaml.safe_load(file)

    profile = dict()
    for key, value in loaded_data.items():
        profile[key] = list()
        for subvalue in value.items():
            profile[key].append(str(subvalue[0]))

            if isinstance(subvalue[1], bool):
                profile[key].append(subvalue[1])
            else:
                profile[key].append(str(subvalue[1]))

    profile_settings = loaded_data["test_settings"]

    return profile, profile_settings

def readSettings(yaml_settings):

    with open(yaml_settings, 'r') as file:
        loaded_data = yaml.safe_load(file)

    
    dictionar = dict()
    for key, value in loaded_data.items():
        dictionar[key] = list()
        for subvalue in value.items():
            dictionar[key].append(subvalue[1])

    settings = dict()
    for key in dictionar.keys():

        enable = dictionar[key][0]
        if type(enable) is not bool:
            enable = False
        else: dictionar[key].pop(0)

        settings[key] = [enable, dictionar[key]]

    return settings