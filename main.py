from collections.abc import MutableMapping

import yaml


def flatten(d, parent_key='', sep='.') -> MutableMapping:
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, MutableMapping):
            items.extend(flatten(v, new_key, sep=sep).items())
        else:
            if isinstance(v, list):
                items.append((new_key, ', '.join(v)))
            else:
                items.append((new_key, v))
    return dict(items)


def main():
    with open("./input/application.yml", mode='rt', encoding='utf-8') as file:
        data = yaml.safe_load_all(file)
        count = 0
        for d in data:
            count += 1
            flattened_map = flatten(d)
            new_file_name = f'application-{flattened_map["spring.config.activate.on-profile"]}.properties'
            with open(f'./output/{new_file_name}', 'w') as new_file:
                for k, v in flattened_map.items():
                    new_file.write(f'{k}={v}\n')
            print(f'wrote {new_file_name}')


if __name__ == '__main__':
    main()
