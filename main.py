import shutil
from collections.abc import MutableMapping

import yaml

PROFILE_DECLARATION_KEYS = ['spring.config.activate.on-profile', 'spring.profiles.active', 'spring.profiles']


def normalize_map(d, parent_key='', sep='.') -> MutableMapping:
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, MutableMapping):
            items.extend(normalize_map(v, new_key, sep=sep).items())
        else:
            if isinstance(v, list):
                items.append((new_key, ','.join(v)))
            else:
                items.append((new_key, v))
    return dict(items)


def main():
    # delete properties file in output folder before running
    shutil.rmtree('./output/*.properties', ignore_errors=True)
    print('output directory cleaned')

    with open("./input/application.yml", mode='rt', encoding='utf-8') as file:
        profiles = yaml.safe_load_all(file)
        for profile in profiles:
            normalized_map = normalize_map(profile)

            profile_key = None
            for key in PROFILE_DECLARATION_KEYS:
                if key in normalized_map:
                    profile_key = key
                    break

            if profile_key in normalized_map:
                if 'local' in normalized_map[profile_key]:
                    new_file_name = f'application-local.properties'
                else:
                    new_file_name = f'application-{normalized_map[profile_key]}.properties'
            else:
                new_file_name = 'application.properties'
            with open(f'./output/{new_file_name}', 'w') as new_file:
                for k, v in normalized_map.items():
                    # skip this prop since we don't need it.
                    if k in PROFILE_DECLARATION_KEYS:
                        continue
                    new_file.write(f'{k}={v}\n')
            print(f'created {new_file_name}')


if __name__ == '__main__':
    main()
