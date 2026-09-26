import glob
import os
import re

import yaml

INPUT_FILE = './input/application.yml'
OUTPUT_DIR = './output'

# Keys that scope a whole YAML document to one or more profiles. spring.profiles.active is deliberately
# not one of them: it *activates* profiles and is kept as a regular property.
ON_PROFILE_KEY = 'spring.config.activate.on-profile'
PROFILE_DECLARATION_KEYS = [ON_PROFILE_KEY, 'spring.profiles']
PROFILE_DECLARATION_PATTERNS = [re.compile(re.escape(key) + r'(\[\d+])?') for key in PROFILE_DECLARATION_KEYS]
ACTIVATION_PREFIX = 'spring.config.activate.'
SHARED_FILE_NAME = 'application.properties'
SIMPLE_PROFILE_NAME = re.compile(r'[\w.-]+')
DOCUMENT_SEPARATOR = '#---'
ESCAPES = {'\\': '\\\\', '\t': '\\t', '\n': '\\n', '\r': '\\r', '\f': '\\f'}


def format_scalar(value) -> str:
    """Render a YAML scalar the way Spring sees it: null is empty and booleans are lowercase."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def normalize_map(value, parent_key='') -> dict:
    """Flatten a YAML document into Spring property keys.

    Nested maps become dotted keys. Lists of scalars become comma separated values, and any other list
    (or one whose items contain commas) becomes indexed keys like ``servers[0].host``.
    """
    if isinstance(value, dict):
        if not value:
            return {parent_key: ''} if parent_key else {}
        items = {}
        for k, v in value.items():
            k = format_scalar(k)
            items.update(normalize_map(v, f'{parent_key}.{k}' if parent_key else k))
        return items
    if isinstance(value, list):
        if not value:
            return {parent_key: ''}
        if all(not isinstance(v, (dict, list)) and ',' not in format_scalar(v) for v in value):
            return {parent_key: ','.join(format_scalar(v) for v in value)}
        items = {}
        for i, v in enumerate(value):
            items.update(normalize_map(v, f'{parent_key}[{i}]'))
        return items
    return {parent_key: format_scalar(value)}


def pop_profiles(props: dict):
    """Remove the profile declaration from a flattened document and return its value, or None."""
    for pattern in PROFILE_DECLARATION_PATTERNS:
        keys = [k for k in props if pattern.fullmatch(k)]
        if keys:
            return ','.join(props.pop(k) for k in keys)
    return None


def escape(text: str, is_key=False) -> str:
    """Escape text for a .properties file. Non-ASCII characters become \\uXXXX so any file encoding works."""
    out = []
    for i, ch in enumerate(text):
        if ch in ESCAPES:
            out.append(ESCAPES[ch])
        elif not ' ' <= ch <= '~':
            # characters outside the BMP are written as a UTF-16 surrogate pair
            utf16 = ch.encode('utf-16-be').hex()
            out.extend('\\u' + utf16[j:j + 4] for j in range(0, len(utf16), 4))
        elif is_key and (ch in '=: ' or (i == 0 and ch in '#!')) or (not is_key and i == 0 and ch == ' '):
            # separators in keys, comment markers at the start of a key and leading spaces in values
            out.append('\\' + ch)
        else:
            out.append(ch)
    return ''.join(out)


def write_properties(path, documents):
    with open(path, 'w', encoding='utf-8') as file:
        for i, props in enumerate(documents):
            if i:
                file.write(DOCUMENT_SEPARATOR + '\n')
            for k, v in props.items():
                file.write(f'{escape(k, is_key=True)}={escape(v)}\n')


def convert(documents, source='input') -> dict:
    """Decide which .properties file each YAML document belongs in.

    ``documents`` are the parsed documents of one YAML file (the parts separated by ``---``). The result maps
    each output file name to the list of documents to write into it. For example, this YAML::

        name: base
        ---
        spring.config.activate.on-profile: prod
        name: prod
        ---
        spring.config.activate.on-profile: prod & cloud
        name: prod-cloud

    is converted into::

        {
            'application.properties': [
                {'name': 'base'},
                {'spring.config.activate.on-profile': 'prod & cloud', 'name': 'prod-cloud'},
            ],
            'application-prod.properties': [{'name': 'prod'}],
        }

    Every file holds a single document, except application.properties: documents that no single file can
    represent are appended to it and written as extra sections separated by '#---'.
    """
    output = {}
    for index, document in enumerate(documents, start=1):
        if document is None:
            continue
        if not isinstance(document, dict):
            raise ValueError(f'YAML document {index} in {source} is not a map')
        # {'server': {'port': 8080}} -> {'server.port': '8080'}
        props = normalize_map(document)
        # take the profile declaration out of the properties:
        # 'spring.config.activate.on-profile: dev, qa' -> profiles 'dev, qa', names ['dev', 'qa']
        # no declaration -> profiles None, names [] (the document holds shared properties)
        profiles = pop_profiles(props)
        names = [p.strip() for p in (profiles or '').split(',') if p.strip()]

        if any(k.startswith(ACTIVATION_PREFIX) for k in props) \
                or not all(SIMPLE_PROFILE_NAME.fullmatch(name) for name in names):
            # The document only applies under a condition that no file name can express, such as a profile
            # expression ('prod & cloud', '!prod') or 'spring.config.activate.on-cloud-platform: kubernetes'.
            # Keep the condition as a property so Spring still evaluates it when it reads the '#---' section:
            #   #---
            #   spring.config.activate.on-profile=prod & cloud
            #   name=prod-cloud
            if profiles is not None:
                props = {ON_PROFILE_KEY: profiles, **props}
            # the first document of application.properties is kept for the shared properties
            output.setdefault(SHARED_FILE_NAME, [{}]).append(props)
        else:
            # Plain profile names map to profile-specific files, and no profile maps to application.properties:
            #   (none)       -> application.properties
            #   'prod'       -> application-prod.properties
            #   'dev, qa'    -> application-dev.properties and application-qa.properties, since a list means
            #                   "active in any of these profiles"
            # Several documents for the same file are merged, and later ones win as they do in Spring:
            #   {'a': '1', 'b': '2'} then {'b': '3'} -> {'a': '1', 'b': '3'}
            for file_name in [f'application-{name}.properties' for name in names] or [SHARED_FILE_NAME]:
                output.setdefault(file_name, [{}])[0].update(props)
    return output


def main(input_file=INPUT_FILE, output_dir=OUTPUT_DIR):
    # convert before touching the output folder, so a bad input file leaves the previous output in place
    with open(input_file, mode='rt', encoding='utf-8') as file:
        output = convert(yaml.safe_load_all(file), source=input_file)

    # delete properties files in output folder before writing
    os.makedirs(output_dir, exist_ok=True)
    for path in glob.glob(os.path.join(output_dir, '*.properties')):
        os.remove(path)
    print('output directory cleaned')

    for file_name, documents in output.items():
        write_properties(os.path.join(output_dir, file_name), documents)
        print(f'created {file_name}')


if __name__ == '__main__':
    main()
